# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

# Base class for fetching data from an ancient database system used by
# swedish gov IT...  FIXME: Now that the ancient database system has
# been retired (early 2016), so should probably this class.
import os
import re
from urllib.parse import quote, urljoin
import codecs

import requests
import lxml.html
from bs4 import BeautifulSoup

from ferenda.decorators import downloadmax
from ferenda.errors import DocumentRemovedError
from ferenda import util
from . import SwedishLegalSource


class NoMoreLinks(Exception):

    def __init__(self, nextpage=None):
        super(NoMoreLinks, self).__init__()
        self.nextpage = nextpage


class Trips(SwedishLegalSource):
    alias = None  # abstract class
    basefile_regex = "(?P<basefile>\d{4}:\d+)$"
    source_encoding = "utf-8"

    @classmethod
    def get_default_options(cls):
        opts = super(Trips, cls).get_default_options()
        opts['ipbasedurls'] = False
        return opts

    def download(self, basefile=None):
        if self.config.ipbasedurls:
            self._make_ipbasedurls()
        if basefile:
            return self.download_single(basefile)
        refresh = self.config.refresh
        updated = False
        for basefile, url in self.download_get_basefiles(None):
            if (refresh or
                    (not os.path.exists(self.store.downloaded_path(basefile)))):
                ret = self.download_single(basefile, url)
                updated = updated or ret
        return updated

    def _make_ipbasedurls(self):
        import socket
        addrs = socket.getaddrinfo("rkrattsbaser.gov.se", 80)
        # grab the first IPv4 number
        ip = [addr[4][0] for addr in addrs if addr[0] == socket.AF_INET][0]
        self.log.warning("Changing rkrattsbaser.gov.se to %s in all URLs" % ip)
        for p in ('start_url',
                  'document_url_template',
                  'document_sfsr_url_template',
                  'document_sfsr_change_url_template'):
            if hasattr(self, p):
                setattr(self, p,
                        getattr(self, p).replace('rkrattsbaser.gov.se',
                                                 ip))

    @downloadmax
    def download_get_basefiles(self, nullparams):
        done = False
        url = self.start_url.format(c=self.config)
        pagecount = 1
        while not done:
            self.log.debug("Starting at %s" % url)
            resp = requests.get(url)
            soup = BeautifulSoup(resp.text, "lxml")
            try:
                for basefile, url in self.download_get_basefiles_page(soup):
                    yield basefile, url
            except NoMoreLinks as e:
                if e.nextpage:
                    pagecount += 1
                    url = e.nextpage
                    self.log.debug("Getting page #%s of results" % pagecount)
                else:
                    done = True

    def download_get_basefiles_page(self, soup):
        nextpage = None
        for hit in soup.findAll("div", "search-hit-info-num"):
            basefile = hit.text.split(": ", 1)[1].strip()
            m = re.search(self.basefile_regex, basefile)
            if m:
                basefile = m.group()
            else:
                self.log.warning("Couldn't find a basefile in this label: %r" % basefile)
                continue
            sbasefile = self.sanitize_basefile(basefile)
            if sbasefile != basefile:
                self.log.warning("%s: normalized from %s" % (sbasefile, basefile))
            year, ordinal = basefile.split(":")
            docurl = self.document_url_template % locals()
            yield(sbasefile, docurl)
        nextpage = soup.find("div", "search-opt-next").a
        if nextpage:
            nextpage = urljoin(self.start_url,
                               nextpage.get("href"))
        raise NoMoreLinks(nextpage)
#
#    def download_single(self, basefile, url=None):
#        # explicitly call superclass' download_single WITHOUT url
#        # parameter. The reason is so that we construct the url
#        # through self.remote_url, which provides permanent urls to
#        # the wanted documents, instead of the temporary/session id
#        # based urls that download_get_basefiles can provide
#        return super(Trips, self).download_single(basefile)
#
    def download_is_different(self, existing, new):
        # load both existing and new into a BeautifulSoup object, then
        # compare the first <pre> element
        existing_soup = BeautifulSoup(
            util.readfile(
                existing,
                encoding=self.source_encoding), "lxml")
        new_soup = BeautifulSoup(util.readfile(new, encoding=self.source_encoding), "lxml")
        try:
            return existing_soup.pre != new_soup.pre
        except RuntimeError: # can happen with at least v4.4.1 of beautifulsoup
            return True

    def remote_url(self, basefile):
        return self.document_url_template % {'basefile': quote(basefile)}

    def metadata_from_basefile(self, basefile):
        a = super(Trips, self).metadata_from_basefile(basefile)
        a["rpubl:arsutgava"], a["rpubl:lopnummer"] = basefile.split(":", 1)
        return a

    def _extract_text(self, basefile, attachment=None):
        intermediate_path = self.store.path(basefile, 'intermediate', '.txt')
        if not attachment and self.store.storage_policy == "dir":
            attachment = "index.html"
        soup = BeautifulSoup(util.readfile(self.store.downloaded_path(
            basefile, attachment=attachment)), "lxml")
        content = soup.find("div", "search-results-content")
        body = content.find("div", "body-text")
        if not body or not body.string:
            raise DocumentRemovedError("%s has no body-text" % basefile,
                                       dummyfile=self.store.parsed_path(basefile))
        body.string = "----------------------------------------------------------------\n\n" + body.string
        txt = content.text
        # the body of the text uses CRLF, but the header uses only
        # LF. Convert to only LF.
        txt = txt.replace("\r", "")
        util.writefile(intermediate_path, txt,
                       encoding=self.source_encoding)
        # I'm not sure whether we should return a binary or text fp,
        # but since this is used by the main parse() logic (which
        # demands binary fp's)...
        # return codecs.open(intermediate_path,
        #                   encoding=self.source_encoding)
        return open(intermediate_path, "rb")


