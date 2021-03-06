# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

import os
import sys
from urllib.parse import quote, unquote
from wsgiref.util import request_uri

from lxml import etree
from rdflib.namespace import DCTERMS

from ferenda import util
from ferenda import TripleStore, Facet, RequestHandler
from ferenda.sources.general import keyword
from ferenda.sources.legal.se import SwedishLegalSource, SFS

class LNKeywordHandler(RequestHandler):
    def supports(self, environ):
        if environ['PATH_INFO'].startswith("/dataset/"):
            return super(LNKeywordHandler, self).supports(environ)
        return environ['PATH_INFO'].startswith("/begrepp/")


class LNKeyword(keyword.Keyword):
    """Manages descriptions of legal concepts (Lagen.nu-version of Keyword)
    """
    requesthandler_class = LNKeywordHandler
    namespaces = SwedishLegalSource.namespaces
    lang = "sv"
    if sys.platform == "darwin":
        collate_locale = "sv_SE.ISO8859-15"
    else:
        collate_locale = "sv_SE.UTF-8"

    def __init__(self, config=None, **kwargs):
        super(LNKeyword, self).__init__(config, **kwargs)
        # FIXME: Don't bother with the large wp download right now
        # (but reinstate later)
        # self.termset_funcs.remove(self.download_termset_wikipedia)
        if self.config._parent and hasattr(self.config._parent, "sfs"):
            self.sfsrepo = SFS(self.config._parent.sfs)
        else:
            self.sfsrepo = SFS()

    def sanitize_term(self, term):
        # attempt to filter out some obvious false positives
        if term.strip()[:-1] in (".", ","):
            return None
        else:
            return term
            
    def canonical_uri(self, basefile):
        # FIXME: make configurable like SFS.canonical_uri
        capitalized = basefile[0].upper() + basefile[1:]
        return 'https://lagen.nu/begrepp/%s' % capitalized.replace(' ', '_')

    def basefile_from_uri(self, uri):
        prefix = "https://lagen.nu/begrepp/"
        if prefix in uri:
            return uri.replace(prefix, "").replace("_", " ")
        else:
            return super(LNKeyword, self).basefile_from_uri(uri)
        
    def _download_termset_mediawiki_titles(self):
        for basefile in self.mediawikirepo.store.list_basefiles_for("parse"):
            if not basefile.startswith("SFS/"):
                yield basefile

    def prep_annotation_file_termsets(self, basefile, main_node):
        dvdataset = self.config.url + "dataset/dv"
        sfsdataset = self.config.url + "dataset/sfs"
        store = TripleStore.connect(self.config.storetype,
                                    self.config.storelocation,
                                    self.config.storerepository)
        legaldefs = self.time_store_select(store,
                                          "sparql/keyword_sfs.rq",
                                          basefile,
                                          sfsdataset,
                                          "legaldefs")
        rattsfall = self.time_store_select(store,
                                          "sparql/keyword_dv.rq",
                                          basefile,
                                          dvdataset,
                                          "legalcases")

        # compatibility hack to enable lxml to process qnames for
        # namespaces FIXME: this is copied from sfs.py -- but could
        # probably be removed once we rewrite this method to use real
        # RDFLib graphs
        def ns(string):
            if ":" in string:
                prefix, tag = string.split(":", 1)
                return "{%s}%s" % (str(self.ns[prefix]), tag)

        for r in rattsfall:
            subject_node = etree.SubElement(main_node, ns("dcterms:subject"))
            rattsfall_node = etree.SubElement(subject_node,
                                              ns("rdf:Description"))
            rattsfall_node.set(ns("rdf:about"), r['uri'])
            id_node = etree.SubElement(rattsfall_node,
                                       ns("dcterms:identifier"))
            id_node.text = r['id']
            desc_node = etree.SubElement(rattsfall_node,
                                         ns("dcterms:description"))
            desc_node.text = r['desc']

        for l in legaldefs:
            subject_node = etree.SubElement(main_node,
                                            ns("rinfoex:isDefinedBy"))
            legaldef_node = etree.SubElement(subject_node,
                                              ns("rdf:Description"))
            legaldef_node.set(ns("rdf:about"), l['uri'])
            id_node = etree.SubElement(legaldef_node, ns("rdfs:label"))
            # id_node.text = "%s %s" % (l['uri'].split("#")[1], l['label'])
            id_node.text = self.sfsrepo.display_title(l['uri'])

        if 'wikipedia\n' in util.readfile(self.store.downloaded_path(basefile)):
            subject_node = etree.SubElement(main_node,
                                            ns("rdfs:seeAlso"))
            link_node = etree.SubElement(subject_node,
                                         ns("rdf:Description"))
            link_node.set(ns("rdf:about"), 'http://sv.wikipedia.org/wiki/' + basefile.replace(" ","_"))
            label_node = etree.SubElement(link_node, ns("rdfs:label"))
            label_node.text = "Begreppet %s finns även beskrivet på svenska Wikipedia" % basefile

    def facets(self):
        def kwselector(row, binding, resource_graph):
            bucket = row[binding][0]
            if bucket.isalpha():
                return bucket.upper()
            else:
                return "#"

        return [Facet(DCTERMS.title,
                      label="Ordnade efter titel",
                      pagetitle='Begrepp som b\xf6rjar p\xe5 "%(selected)s"',
                      selector=kwselector)
        ]

    # override simply to be able to specify that title/A should be first, not title/#
    def toc_generate_first_page(self, pagecontent, pagesets, otherrepos=[]):
        """Generate the main page of TOC pages."""
        for firstpage in pagesets[0].pages:
            if firstpage.value == "a":
                break
        else:
            firstpage = pagesets[0].pages[0]
        documents = pagecontent[(firstpage.binding, firstpage.value)]
        return self.toc_generate_page(firstpage.binding, firstpage.value,
                                      documents, pagesets, "index", otherrepos)

        
    def tabs(self):
        return [("Begrepp", self.dataset_uri())]

    def frontpage_content(self, primary=False):
        if not self.config.tabs:
            self.log.debug("%s: Not doing frontpage content (config has tabs=False)" % self.alias)
            return
        x = self.tabs()[0]
        label = x[0]
        uri = x[1]
        body = self.frontpage_content_body()
        return ("<h2><a href='%(uri)s'>%(label)s</a></h2>"
                "<p>%(body)s</p>" % locals())

    def frontpage_content_body(self):
        return "%s begrepp" % len(set([row['uri'] for row in self.faceted_data()]))
        

