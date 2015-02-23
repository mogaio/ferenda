# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

import os
import re
import logging
import codecs
from tempfile import mktemp
from xml.sax.saxutils import escape as xml_escape

from rdflib import Graph, URIRef, Literal, Namespace
from bs4 import BeautifulSoup
import requests
import six
from six.moves.urllib_parse import urljoin, unquote
import lxml.html

from ferenda import TextReader, Describer, Facet, DocumentRepository
from ferenda import util, decorators
from ferenda.elements import Body, Page, Preformatted, Link
from ferenda.sources.legal.se.legalref import LegalRef
from ferenda.sources.legal.se import legaluri
from . import SwedishLegalSource
from .swedishlegalsource import SwedishCitationParser

from rdflib import RDF
from rdflib.namespace import DCTERMS, SKOS
from . import RPUBL
PROV = Namespace(util.ns['prov'])
RINFOEX = Namespace("http://lagen.nu/terms#")

class MyndFskr(SwedishLegalSource):

    """A abstract base class for fetching and parsing regulations from
    various swedish government agencies. These documents often have a
    similar structure both linguistically and graphically (most of the
    time they are in similar PDF documents), enabling us to parse them
    in a generalized way. (Downloading them often requires
    special-case code, though.)

    """
    source_encoding = "utf-8"
    downloaded_suffix = ".pdf"
    alias = 'myndfskr'


    rdf_type = (RPUBL.Myndighetsforeskrift, RPUBL.AllmannaRad) 
    required_predicates = [RDF.type, DCTERMS.title,
                           DCTERMS.identifier, RPUBL.arsutgava,
                           DCTERMS.publisher, RPUBL.beslutadAv,
                           RPUBL.beslutsdatum,
                           RPUBL.forfattningssamling,
                           RPUBL.ikrafttradandedatum, RPUBL.lopnummer,
                           RPUBL.utkomFranTryck, PROV.wasGeneratedBy]
    sparql_annotations = None  # until we can speed things up

    basefile_regex = re.compile('(?P<basefile>\d{4}[:/_-]\d+)(?:|\.\w+)$')
    document_url_regex = re.compile('(?P<basefile>\d{4}[:/_-]\d+)(?:|\.\w+)$')

    nextpage_regex = None
    nextpage_url_regex = None
    download_rewrite_url = False # iff True, use remote_url to rewrite
                                 # download links instead of accepting
                                 # found links as-is
    download_formid = None # if the paging uses forms, POSTs and other
                           # forms of insanity

    def forfattningssamlingar(self):
        return [self.alias]


    @decorators.downloadmax
    def download_get_basefiles(self, source):
        # this is an extended version of
        # DocumentRepository.download_get_basefiles which handles
        # "next page" navigation and also ensures that the default
        # basefilepattern is "myndfs/2015:1", not just "2015:1"
        yielded = set()
        while source:
            nextform = nexturl = None
            for (element, attribute, link, pos) in source:
                basefile = None

                # Two step process: First examine link text to see if
                # basefile_regex match. If not, examine link url to see
                # if document_url_regex
                if (self.basefile_regex and
                    element.text and
                        re.search(self.basefile_regex, element.text)):
                    m = re.search(self.basefile_regex, element.text)
                    basefile = m.group("basefile")
                elif self.document_url_regex and re.match(self.document_url_regex, link):
                    m = re.match(self.document_url_regex, link)
                    if m:
                        basefile = m.group("basefile")

                if basefile:
                    if not any((basefile.startswith(fs+"/") for fs in self.forfattningssamlingar())):
                        basefile = self.forfattningssamlingar()[0] + "/" + basefile

                    if self.download_rewrite_url:
                        link = self.remote_url(basefile)
                    if basefile not in yielded:
                        yield (basefile, link)
                        yielded.add(basefile)
                if (self.nextpage_regex and element.text and
                    re.search(element.text, self.nextpage_regex)):
                    nexturl = link
                elif (self.nextpage_url_regex and
                      re.search(link, self.nextpage_url_regex)):
                    nexturl = link
                if (self.download_formid and
                    element.tag == "form" and
                    element.get("id") == self.download_formid):
                    nextform = element
            if nextform is not None and nexturl is not None:
                resp = self.download_post_form(nextform, nexturl)
            elif nexturl is not None:
                resp = self.session.get(nexturl)
            else:
                resp = None
                source = None

            if resp:
                tree = lxml.html.document_fromstring(resp.text)
                tree.make_links_absolute(nextform.get("action"),
                                         resolve_base_href=True)
                source = tree.iterlinks()


    def download_post_form(self, form, url):
        raise NotImplementedError


    def canonical_uri(self, basefile):
        # The canonical URI for these documents cannot always be
        # computed from the basefile. Find the primary subject of the
        # distilled RDF graph instead.
        if not os.path.exists(self.store.distilled_path(basefile)):
            return None

        g = Graph()
        g.parse(self.store.distilled_path(basefile))
        subjects = list(g.subject_objects(RDF.type))

        if subjects:
            return str(subjects[0][0])
        else:
            self.log.warning(
                "No canonical uri in %s" % (self.distilled_path(basefile)))
            return None
            
    @decorators.action
    @decorators.managedparsing
    def parse(self, doc):
        # This has a similar structure to DocumentRepository.parse but
        # works on PDF docs converted to plaintext, instead of HTML
        # trees.
        reader = self.textreader_from_basefile(doc.basefile)
        self.parse_metadata_from_textreader(reader, doc)
        self.parse_document_from_textreader(reader, doc)
        self.parse_entry_update(doc)
        return True  # Signals that everything is OK

    def textreader_from_basefile(self, basefile):
        infile = self.store.downloaded_path(basefile)
        tmpfile = self.store.path(basefile, 'intermediate', '.pdf')
        outfile = self.store.path(basefile, 'intermediate', '.txt')
        util.copy_if_different(infile, tmpfile)
        # this command will create a file named as the val of outfile
        util.runcmd("pdftotext %s" % tmpfile, require_success=True)
        util.robust_remove(tmpfile)
        return TextReader(outfile, self.source_encoding,
                          linesep=TextReader.UNIX)

    def fwdtests(self):
        return {'dcterms:issn': ['^ISSN (\d+\-\d+)$'],
                'dcterms:title':
                ['((?:Föreskrifter|[\w ]+s (?:föreskrifter|allmänna råd)).*?)\n\n'],
                'dcterms:identifier': ['^([A-ZÅÄÖ-]+FS\s\s?\d{4}:\d+)$'],
                'rpubl:utkomFranTryck':
                ['Utkom från\strycket\s+den\s(\d+ \w+ \d{4})'],
                'rpubl:omtryckAv': ['^(Omtryck)$'],
                'rpubl:genomforDirektiv': ['Celex (3\d{2,4}\w\d{4})'],
                'rpubl:beslutsdatum':
                ['(?:har beslutats|beslutade|beslutat) den (\d+ \w+ \d{4})'],
                'rpubl:beslutadAv':
                ['\n([A-ZÅÄÖ][\w ]+?)\d? (?:meddelar|lämnar|föreskriver)',
                 '\s(?:meddelar|föreskriver) ([A-ZÅÄÖ][\w ]+?)\d?\s'],
                'rpubl:bemyndigande':
                [' ?(?:meddelar|föreskriver|Föreskrifterna meddelas|Föreskrifterna upphävs)\d?,? (?:följande |)med stöd av\s(.*?) ?(?:att|efter\ssamråd|dels|följande|i fråga om|och lämnar allmänna råd|och beslutar följande allmänna råd|\.\n)',
                 '^Med stöd av (.*)\s(?:meddelar|föreskriver)']
            }

    def revtests(self):
        return {'rpubl:ikrafttradandedatum':
                ['(?:Denna författning|Dessa föreskrifter|Dessa allmänna råd|Dessa föreskrifter och allmänna råd)\d* träder i ?kraft den (\d+ \w+ \d{4})',
                 'Dessa föreskrifter träder i kraft, (?:.*), i övrigt den (\d+ \w+ \d{4})',
                 'ska(?:ll|)\supphöra att gälla (?:den |)(\d+ \w+ \d{4}|denna dag|vid utgången av \w+ \d{4})',
                 'träder i kraft den dag då författningen enligt uppgift på den (utkom från trycket)'],
                'rpubl:upphaver':
                ['träder i kraft den (?:\d+ \w+ \d{4}), då(.*)ska upphöra att gälla',
                 'ska(?:ll|)\supphöra att gälla vid utgången av \w+ \d{4}, nämligen(.*?)\n\n',
                 'att (.*) skall upphöra att gälla (denna dag|vid utgången av \w+ \d{4})']
        }

    def parse_metadata_from_textreader(self, reader, doc):
        g = doc.meta

        # 1. Find some of the properties on the first page (or the
        #    2nd, or 3rd... continue past TOC pages, cover pages etc
        #    until the "real" first page is found) NB: FFFS 2007:1
        #    has ten (10) TOC pages!
        pagecount = 0
        for page in reader.getiterator(reader.readpage):
            pagecount += 1
            props = {}
            for (prop, tests) in list(self.fwdtests().items()):
                if prop in props:
                    continue
                for test in tests:
                    m = re.search(
                        test, page, re.MULTILINE | re.DOTALL | re.UNICODE)
                    if m:
                        props[prop] = util.normalize_space(m.group(1))
            # Single required propery. If we find this, we're done
            if 'rpubl:beslutsdatum' in props:
                break
            self.log.warning("%s: Couldn't find required props on page %s" %
                             (doc.basefile, pagecount))

        # 2. Find some of the properties on the last 'real' page (not
        #    counting appendicies)
        reader.seek(0)
        pagesrev = reversed(list(reader.getiterator(reader.readpage)))
        # The language used to expres these two properties differ
        # quite a lot, more than what is reasonable to express in a
        # single regex. We therefore define a set of possible
        # expressions and try them in turn.
        revtests = self.revtests()
        cnt = 0
        for page in pagesrev:
            cnt += 1
            # Normalize the whitespace in each paragraph so that a
            # linebreak in the middle of the natural language
            # expression doesn't break our regexes.
            page = "\n\n".join(
                [util.normalize_space(x) for x in page.split("\n\n")])

            for (prop, tests) in list(revtests.items()):
                if prop in props:
                    continue
                for test in tests:
                    # Not re.DOTALL -- we've normalized whitespace and
                    # don't want to match across paragraphs
                    m = re.search(test, page, re.MULTILINE | re.UNICODE)
                    if m:
                        props[prop] = util.normalize_space(m.group(1))

            # Single required propery. If we find this, we're done
            if 'rpubl:ikrafttradandedatum' in props:
                break

        self.sanitize_metadata(props, doc)
        self.polish_metadata(props, doc)
        self.infer_triples(Describer(doc.meta, doc.uri), doc)
        return doc

    def sanitize_metadata(self, props, doc):
        """Correct those irregularities in the extracted metadata that we can
           find"""

        # common false positive
        if 'dcterms:title' in props:
            if 'denna f\xf6rfattning har beslutats den' in props['dcterms:title']:
                del props['dcterms:title']
            elif "\nbeslutade den " in props['dcterms:title']:
                # sometimes the title isn't separated with two
                # newlines from the rest of the text
                props['dcterms:title'] = props[
                    'dcterms:title'].split("\nbeslutade den ")[0]
        if 'rpubl:bemyndigande' in props:
            props['rpubl:bemyndigande'] = props[
                'rpubl:bemyndigande'].replace('\u2013', '-')


    def polish_metadata(self, props, doc):
        """Clean up data, including converting a string->string dict to a
        proper RDF graph.

        """
        if self.config.localizeuri:
            f = SwedishCitationParser(None, self.config.url,
                                      self.config.urlpath).localize_uri
            def makeurl(data):
                return f(legaluri.construct(data))
        else:
            makeurl = legaluri.construct
            
        # FIXME: this code should go into canonical_uri, if we can
        # find a way to give it access to props['dcterms:identifier']
        if 'dcterms:identifier' in props:
            (pub, year, ordinal) = re.split('[ :]',
                                            props['dcterms:identifier'])
        else:
            # simple inference from basefile
            (pub, year, ordinal) = re.split('[ :]',
                                            props['dcterms:identifier'])
        uri = makeurl({'type': LegalRef.FORESKRIFTER,
                       'publikation': pub,
                       'artal': year,
                       'lopnummer': ordinal})

        if doc.uri is not None and uri != doc.uri:
            self.log.warning("Assumed URI would be %s but it turns out to be %s"% (doc.uri, uri))
        doc.uri = uri
        desc = Describer(doc.meta, doc.uri)


        fs = self.lookup_resource(pub, SKOS.altLabel)
        desc.rel(RPUBL.forfattningssamling, fs)
        # publisher for the series == publisher for the document
        desc.rel(DCTERMS.publisher,
                 self.commondata.value(fs, DCTERMS.publisher))
                     
        desc.value(RPUBL.arsutgava, year)
        desc.value(RPUBL.lopnummer, ordinal)
        desc.value(DCTERMS.identifier, props['dcterms:identifier'])

        if 'rpubl:beslutadAv' in props:
            desc.rel(RPUBL.beslutadAv,
                     self.lookup_resource(props['rpubl:beslutadAv']))

        if 'dcterms:issn' in props:
            desc.value(DCTERMS.issn, props['dcterms:issn'])

        if 'dcterms:title' in props:
            desc.value(DCTERMS.title,
                       Literal(util.normalize_space(
                           props['dcterms:title']), lang="sv"))

            if re.search('^(Föreskrifter|[\w ]+s föreskrifter) om ändring i ',
                         props['dcterms:title'], re.UNICODE):
                orig = re.search('([A-ZÅÄÖ-]+FS \d{4}:\d+)',
                                 props['dcterms:title']).group(0)
                (publication, year, ordinal) = re.split('[ :]', orig)
                origuri = makeurl({'type': LegalRef.FORESKRIFTER,
                                   'publikation': pub,
                                   'artal': year,
                                   'lopnummer': ordinal})
                desc.rel(RPUBL.andrar,
                         URIRef(origuri))

            # FIXME: is this a sensible value for rpubl:upphaver
            if (re.search('^(Föreskrifter|[\w ]+s föreskrifter) om upphävande '
                          'av', props['dcterms:title'], re.UNICODE)
                    and not 'rpubl:upphaver' in props):
                props['rpubl:upphaver'] = props['dcterms:title']

        for key, pred in (('rpubl:utkomFranTryck', RPUBL.utkomFranTryck),
                          ('rpubl:beslutsdatum', RPUBL.beslutsdatum),
                          ('rpubl:ikrafttradandedatum', RPUBL.ikrafttradandedatum)):
            if key in props:
                # FIXME: how does this even work
                if (props[key] == 'denna dag' and
                        key == 'rpubl:ikrafttradandedatum'):
                    desc.value(RPUBL.ikrafttradandedatum,
                               self.parse_swedish_date(props['rpubl:beslutsdatum']))
                elif (props[key] == 'utkom från trycket' and
                      key == 'rpubl:ikrafttradandedatum'):
                    desc.value(RPUBL.ikrafttradandedatum,
                               self.parse_swedish_date(props['rpubl:utkomFranTryck']))
                else:
                    desc.value(pred,
                               self.parse_swedish_date(props[key].lower()))

        if 'rpubl:genomforDirektiv' in props:
            makeurl({'type': LegalRef.EULAGSTIFTNING,
                     'celex':
                     props['rpubl:genomforDirektiv']})
            desc.rel(RPUBL.genomforDirektiv, diruri)

        has_bemyndiganden = False
        if 'rpubl:bemyndigande' in props:
            # FIXME: move to sanitize_metadata
            # SimpleParse can't handle unicode endash sign, transform
            # into regular ascii hyphen
            props['rpubl:bemyndigande'] = props[
                'rpubl:bemyndigande'].replace('\u2013', '-')
            parser = LegalRef(LegalRef.LAGRUM)
            result = parser.parse(props['rpubl:bemyndigande'])
            bemyndiganden = [x.uri for x in result if hasattr(x, 'uri')]

            # some of these uris need to be filtered away due to
            # over-matching by parser.parse
            filtered_bemyndiganden = []
            for bem_uri in bemyndiganden:
                keep = True
                for compare in bemyndiganden:
                    if (len(compare) > len(bem_uri) and
                            compare.startswith(bem_uri)):
                        keep = False
                if keep:
                    filtered_bemyndiganden.append(bem_uri)

            for bem_uri in filtered_bemyndiganden:
                desc.rel(RPUBL.bemyndigande, bem_uri)

        if 'rpubl:upphaver' in props:
            for upph in re.findall('([A-ZÅÄÖ-]+FS \d{4}:\d+)',
                                   util.normalize_space(props['rpubl:upphaver'])):
                (pub, year, ordinal) = re.split('[ :]', upph)
                upphuri = legaluri.construct({'type': LegalRef.FORESKRIFTER,
                                              'publikation': pub,
                                              'artal': year,
                                              'lopnummer': ordinal})
                desc.rel(RPUBL.upphaver, upphuri)

        if ('dcterms:title' in props and
            "allmänna råd" in props['dcterms:title'] and
                "föreskrifter" not in props['dcterms:title']):
            rdftype = RPUBL.AllmannaRad
        else:
            rdftype = RPUBL.Myndighetsforeskrift
        desc.rdftype(rdftype)
        desc.value(self.ns['prov'].wasGeneratedBy, self.qualified_class_name())
        if RPUBL.bemyndigande in self.required_predicates:
            self.required_predicates.pop(self.required_predicates.index(RPUBL.bemyndigande))
        if rdftype == RPUBL.Myndighetsforeskrift:
            self.required_predicates.append(RPUBL.bemyndigande)


    def parse_document_from_textreader(self, reader, doc):
        # Create data for the body, removing various control characters
        # TODO: Use pdftohtml to create a nice viewable HTML
        # version instead of this plaintext stuff
        reader.seek(0)
        body = Body()

        # A fairly involved way of filtering out all control
        # characters from a string
        import unicodedata
        if six.PY3:
            all_chars = (chr(i) for i in range(0x10000))
        else:
            all_chars = (unichr(i) for i in range(0x10000))
        control_chars = ''.join(
            c for c in all_chars if unicodedata.category(c) == 'Cc')
        # tab and newline are technically Control characters in
        # unicode, but we want to keep them.
        control_chars = control_chars.replace("\t", "").replace("\n", "")

        control_char_re = re.compile('[%s]' % re.escape(control_chars))
        for idx, page in enumerate(reader.getiterator(reader.readpage)):
            text = xml_escape(control_char_re.sub('', page))
            p = Page(ordinal=idx+1)
            p.append(Preformatted(text))
            body.append(p)
        doc.body = body

    def facets(self):
        return [Facet(RDF.type),
                Facet(DCTERMS.title),
                Facet(DCTERMS.publisher),
                Facet(DCTERMS.identifier),
                Facet(RPUBL.arsutgava,
                      use_for_toc=True)]

    def basefile_from_uri(self, uri):
        for fs in self.forfattningssamlingar():
            prefix = self.config.url + fs + "/"
            if uri.startswith(prefix) and uri[len(prefix)].isdigit():
                rest = uri[len(prefix):].replace("_", " ")
                return rest.split("/")[0]

    def toc_item(self, binding, row):
        """Returns a formatted version of row, using Element objects"""
        # more defensive version of DocumentRepository.toc_item
        label = ""
        if 'dcterms_identifier' in row:
            label = row['dcterms_identifier']
        else:
            self.log.warning("No dcterms:identifier for %s" % row['uri'])
            
        if 'dcterms_title' in row:
            label += ": " + row['dcterms_title']
        else:
            self.log.warning("No dcterms:title for %s" % row['uri'])
            label = "URI: " + row['uri']
        return [Link(label, uri=row['uri'])]

    def tabs(self, primary=False):
        return [(self.__class__.__name__, self.dataset_uri())]


class SJVFS(MyndFskr):
    alias = "sjvfs"
    forfattningssamlingar = ["sjvfs", "dfs"]
    start_url = "http://www.jordbruksverket.se/forfattningar/forfattningssamling.4.5aec661121e2613852800012537.html"
    

    def download(self, basefile=None):
        self.session = requests.session()
        soup = BeautifulSoup(self.session.get(self.start_url).text)
        main = soup.find_all("li", "active")
        assert len(main) == 1
        extra = []
        for a in list(main[0].ul.find_all("a")):
            # only fetch subsections that start with a year, not
            # "Allmänna råd"/"Notiser"/"Meddelanden"
            if a.text.split()[0].isdigit():
                url = urljoin(self.start_url, a['href'])
                self.log.info("Fetching %s %s" % (a.text, url))
                extra.extend(self.download_indexpage(url))


    def download_indexpage(self, url):
        subsoup = BeautifulSoup(self.session.get(url).text)
        submain = subsoup.find("div", "pagecontent")
        extrapages = []
        for a in submain.find_all("a"):
            if a['href'].endswith(".pdf") or a['href'].endswith(".PDF"):
                if re.search('\d{4}:\d+', a.text):
                    m = re.search('(\w+FS|) ?(\d{4}:\d+)', a.text)
                    fs = m.group(1).lower()
                    fsnr = m.group(2)
                    if not fs:
                        fs = "sjvfs"
                    basefile = "%s/%s" % (fs, fsnr)
                    suburl = unquote(
                        urljoin(url, a['href']))
                    self.download_single(basefile, url=suburl)
                elif a.text == "Besult":
                    basefile = a.find_parent(
                        "td").findPreviousSibling("td").find("a").text
                    self.log.debug(
                        "Will download beslut to %s (later)" % basefile)
                elif a.text == "Bilaga":
                    basefile = a.find_parent(
                        "td").findPreviousSibling("td").find("a").text
                    self.log.debug(
                        "Will download bilaga to %s (later)" % basefile)
                elif a.text == "Rättelseblad":
                    basefile = a.find_parent(
                        "td").findPreviousSibling("td").find("a").text
                    self.log.debug(
                        "Will download rättelseblad to %s (later)" % basefile)
                else:
                    self.log.debug("I don't know what to do with %s" % a.text)
            else:
                suburl = urljoin(url, a['href'])
                extrapages.append(suburl)
        return extrapages

    def basefile_from_uri(self, uri):
        # this should map https://lagen.nu/sjvfs/2014:9 to basefile sjvfs/2014:9
        # but also https://lagen.nu/dfs/2007:8 -> dfs/2007:8
        prefix = self.config.url + self.config.urlpath
        altprefix = self.config.url + self.config.altpath
        if uri.startswith(prefix) or uri.startswith(altprefix):
            basefile = uri[len(self.config.url):]
            return basefile


class FFFS(MyndFskr):
    alias = "fffs"
    start_url = "http://www.fi.se/Regler/FIs-forfattningar/Forteckning-FFFS/"
    document_url = "http://www.fi.se/Regler/FIs-forfattningar/Samtliga-forfattningar/%s/"
    storage_policy = "dir"  # must be able to handle attachments

    def download(self, basefile=None):
        self.session = requests.session()
        soup = BeautifulSoup(self.session.get(self.start_url).text)
        main = soup.find(id="fffs-searchresults")
        docs = []
        for numberlabel in main.find_all(text=re.compile('\s*Nummer\s*')):
            ndiv = numberlabel.find_parent('div').parent
            typediv = ndiv.findNextSibling()
            if typediv.find('div', 'FFFSListAreaLeft').get_text(strip=True) != "Typ":
                self.log.error("Expected 'Typ' in div, found %s" %
                               typediv.get_text(strip=True))
                continue

            titlediv = typediv.findNextSibling()
            if titlediv.find('div', 'FFFSListAreaLeft').get_text(strip=True) != "Rubrik":
                self.log.error("Expected 'Rubrik' in div, found %s" %
                               titlediv.get_text(strip=True))
                continue

            number = ndiv.find('div', 'FFFSListAreaRight').get_text(strip=True)
            basefile = "fffs/"+number
            tmpfile = mktemp()
            with self.store.open_downloaded(basefile, mode="w", attachment="snippet.html") as fp:
                fp.write(str(ndiv))
                fp.write(str(typediv))
                fp.write(str(titlediv))
            self.download_single(basefile)

    # FIXME: This should create/update the documententry!!
    def download_single(self, basefile):
        pdffile = self.store.downloaded_path(basefile)
        self.log.debug("%s: download_single..." % basefile)
        snippetfile = self.store.downloaded_path(basefile, attachment="snippet.html")
        soup = BeautifulSoup(open(snippetfile))
        href = soup.find(text=re.compile("\s*Rubrik\s*")).find_parent("div", "FFFSListArea").a.get("href")
        url = urljoin("http://www.fi.se/Regler/FIs-forfattningar/Forteckning-FFFS/", href)
        if href.endswith(".pdf"):
            self.download_if_needed(url, basefile)

        elif "/Samtliga-forfattningar/" in href:
            self.log.debug("%s: Separate page" % basefile)
            self.download_if_needed(url, basefile,
                                    filename=self.store.downloaded_path(basefile, attachment="description.html"))
            descriptionfile = self.store.downloaded_path(basefile, attachment="description.html")
            soup = BeautifulSoup(open(descriptionfile))
            for link in soup.find("div", "maincontent").find_all("a"):
                suburl = urljoin(url, link['href']).replace(" ", "%20")
                if link.text.strip().startswith('Grundförfattning'):
                    if self.download_if_needed(suburl, basefile):
                        self.log.info("%s: downloaded main PDF" % basefile)

                elif link.text.strip().startswith('Konsoliderad version'):
                    if self.download_if_needed(suburl, basefile,
                                               filename=self.store.downloaded_path(basefile, attachment="konsoliderad.pdf")):
                        self.log.info(
                            "%s: downloaded consolidated PDF" % basefile)

                elif link.text.strip().startswith('Ändringsförfattning'):
                    self.log.info("Skipping change regulation")
                elif link['href'].endswith(".pdf"):
                    filename = link['href'].split("/")[-1]
                    if self.download_if_needed(suburl, basefile, self.store.downloaded_path(basefile, attachment=filename)):
                        self.log.info("%s: downloaded '%s' to %s" %
                                      (basefile, link.text, filename))

        else:
            self.log.warning("%s: No idea!" % basefile)



class ELSAKFS(MyndFskr):
    alias = "elsakfs"  # real name is ELSÄK-FS, but avoid swedchars, uppercase and dashes
    uri_slug = "elsaek-fs"  # for use in

    start_url = "http://www.elsakerhetsverket.se/sv/Lag-och-ratt/Foreskrifter/Elsakerhetsverkets-foreskrifter-listade-i-nummerordning/"


class NFS(MyndFskr):
    alias = "nfs"

    start_url = "http://www.naturvardsverket.se/sv/Start/Lagar-och-styrning/Foreskrifter-och-allmanna-rad/Foreskrifter/"


class STAFS(MyndFskr):
    alias = "stafs"
    re_identifier = re.compile('STAFS (\d{4})[:/_-](\d+)')

    start_url = "http://www.swedac.se/sv/Det-handlar-om-fortroende/Lagar-och-regler/Alla-foreskrifter-i-nummerordning/"

    def download(self, basefile=None):
        self.session = requests.session()
        soup = BeautifulSoup(self.session.get(self.start_url).text)
        for link in list(soup.find_all("a", href=re.compile('/STAFS/'))):
            basefile = re.search('\d{4}:\d+', link.text).group(0)
            self.download_single(basefile, urljoin(self.start_url, link['href']))

    def download_single(self, basefile, url):
        self.log.info("%s: %s" % (basefile, url))
        consolidated_link = None
        newest = None
        soup = BeautifulSoup(self.session.get(url).text)
        for link in soup.find_all("a", text=self.re_identifier):
            self.log.info("   %s: %s %s" % (basefile, link.text, link.url))
            if "konso" in link.text:
                consolidated_link = link
            else:
                m = self.re_identifier.search(link.text)
                assert m
                if link.url.endswith(".pdf"):
                    basefile = m.group(1) + ":" + m.group(2)
                    filename = self.store.downloaded_path(basefile)
                    self.log.info("        Downloading to %s" % filename)
                    self.download_if_needed(link.absolute_url, filename)
                    if basefile > newest:
                        self.log.debug(
                            "%s larger than %s" % (basefile, newest))
                        consolidated_basefile = basefile + \
                            "/konsoliderad/" + basefile
                        newest = basefile
                    else:
                        self.log.debug(
                            "%s not larger than %s" % (basefile, newest))
                else:
                    # not pdf - link to yet another pg
                    subsoup = BeautifulSoup(self.session.get(link).text)
                    for sublink in soup.find_all("a", text=self.re_identifier):
                        self.log.info("   Sub %s: %s %s" %
                                      (basefile, sublink.text, sublink['href']))
                        m = self.re_identifier.search(sublink.text)
                        assert m
                        if sublink.url.endswith(".pdf"):
                            subbasefile = m.group(1) + ":" + m.group(2)
                            self.download_if_needed(urljoin(link, sublink['href'], subbasefile))

        if consolidated_link:
            filename = self.store.downloaded_path(consolidated_basefile)
            self.log.info("        Downloading consd to %s" % filename)
            self.download_if_needed(
                consolidated_link.absolute_url, consolidated_basefile, filename=filename)


class SKVFS(MyndFskr):
    alias = "skvfs"
    source_encoding = "utf-8"
    downloaded_suffix = ".pdf"

    # start_url = "http://www.skatteverket.se/rattsinformation/foreskrifter/tidigarear.4.1cf57160116817b976680001670.html"
    # This url contains slightly more (older) links (and a different layout)?
    start_url = "http://www.skatteverket.se/rattsinformation/lagrummet/foreskriftergallande/aldrear.4.19b9f599116a9e8ef3680003547.html"

    # also consolidated versions
    # http://www.skatteverket.se/rattsinformation/lagrummet/foreskrifterkonsoliderade/aldrear.4.19b9f599116a9e8ef3680004242.html

    # URL's are highly unpredictable. We must find the URL for every
    # resource we want to download, we cannot transform the resource
    # id into a URL
    def download(self, basefile=None):
        self.log.info("Starting at %s" % self.start_url)
        years = {}
        self.session = requests.session()
        soup = BeautifulSoup(self.session.get(self.start_url).text)
        for link in sorted(list(soup.find_all("a", text=re.compile('^\d{4}$'))),
                           key=attrgetter('text')):
            year = int(link.text)
            # Documents for the years 1985-2003 are all on one page
            # (with links leading to different anchors). To avoid
            # re-downloading stuff when usecache=False, make sure we
            # haven't seen this url (sans fragment) before
            url = link.absolute_url.split("#")[0]
            if year not in years and url not in list(years.values()):
                self.download_year(year, url)
                years[year] = url

    # just download the most recent year
    def download_new(self):
        self.log.info("Starting at %s" % self.start_url)
        soup = BeautifulSoup(self.session.get(self.start_url).text)
        link = sorted(list(soup.find_all("a", text=re.compile('^\d{4}$'))),
                      key=attrgetter('text'), reverse=True)[0]
        self.download_year(int(link.text), link.absolute_url, usecache=True)

    def download_year(self, year, url):
        self.log.info("Downloading year %s from %s" % (year, url))
        soup = BeautifulSoup(self.session.get(self.start_url).text)
        for link in soup.find_all("a", text=re.compile('FS \d+:\d+')):
            if "bilaga" in link.text:
                self.log.warning("Skipping attachment in %s" % link.text)
                continue

            # sanitize trailing junk
            linktext = re.match("\w+FS \d+:\d+", link.text).group(0)
            # something like skvfs/2010/23 or rsfs/1996/9
            basefile = linktext.strip(
            ).lower().replace(" ", "/").replace(":", "/")
            self.download_single(
                basefile, link.absolute_url)

    def download_single(self, basefile, url):
        self.log.info("Downloading %s from %s" % (basefile, url))
        self.document_url = url + "#%s"
        html_downloaded = super(
            SKVFS, self).download_single(basefile)
        year = int(basefile.split("/")[1])
        if year >= 2007:  # download pdf as well
            filename = self.store.downloaded_path(basefile)
            pdffilename = os.path.splitext(filename)[0] + ".pdf"
            if not os.path.exists(pdffilename):
                soup = self.soup_from_basefile(basefile)
                pdflink = soup.find(href=re.compile('\.pdf$'))
                if not pdflink:
                    self.log.debug("No PDF file could be found")
                    return html_downloaded
                pdftext = pdflink.get_text(strip=True)
                pdfurl = urljoin(url, pdflink['href'])
                self.log.debug("Found %s at %s" % (pdftext, pdfurl))
                pdf_downloaded = self.download_if_needed(pdfurl, pdffilename)
                return html_downloaded and pdf_downloaded
            else:
                return False
        else:
            return html_downloaded

class DIFS(MyndFskr):
    alias = "difs"
    start_url = "http://www.datainspektionen.se/lagar-och-regler/datainspektionens-foreskrifter/"
    

class SOSFS(MyndFskr):
    alias = "sosfs"
    start_url = "http://www.socialstyrelsen.se/sosfs"
    storage_policy = "dir"  # must be able to handle attachments
    download_iterlinks = False

    def _basefile_from_text(self, linktext):
        if linktext:
            m = re.search("SOSFS\s+(\d+:\d+)", linktext)
            if m:
                return m.group(1)

    @decorators.downloadmax
    def download_get_basefiles(self, source):
        soup = BeautifulSoup(source)
        for td in soup.find_all("td", "col3"):
            txt = td.get_text().strip()
            basefile = self._basefile_from_text(txt)
            if basefile is None:
                continue
            link_el = td.find_previous_sibling("td").a
            link = urljoin(self.start_url, link_el.get("href"))
            if link.startswith("javascript:"):
                continue
            # If a base act has no changes, only type 1 links will be
            # on the front page. If it has any changes, only a type 2
            # link will be on the front page, but type 1 links will be
            # on that subsequent page.
            if (txt.startswith("Grundförfattning") or
                txt.startswith("Ändringsförfattning")):
                # 1) links to HTML pages describing (and linking to) a
                # base act, eg for SOSFS 2014:10 
                # http://www.socialstyrelsen.se/publikationer2014/2014-10-12
                yield(basefile, link)
            elif txt.startswith("Konsoliderad"):
                # 2) links to HTML pages containing a consolidated act
                # (with links to type 1 base and change acts), eg for
                # SOSFS 2011:13
                # http://www.socialstyrelsen.se/sosfs/2011-13 - fetch
                # page, yield all type 1 links, also find basefile form
                # element.text
                soup = BeautifulSoup(self.session.get(link).text)
                self.log.debug("%s: Downloading all base/change acts" % basefile)
                for link_el in soup.find(text="Ladda ner eller beställ").find_parent("div").find_all("a"):
                    if '/publikationer' in link_el.get("href"):
                        subbasefile = self._basefile_from_text(link_el.get_text())
                        if subbasefile:
                            yield(subbasefile,
                                  urljoin(link, link_el.get("href")))
                # then save page itself as grundforf/konsoldering.html
                konsfile = self.store.downloaded_path(basefile, attachment="konsolidering.html")
                self.log.debug("%s: Downloading consolidated version" % basefile)
                self.download_if_needed(link, basefile, filename=konsfile)

    # FIXME: update documententry!
    def download_single(self, basefile, url):
        resp = self.session.get(url)
        soup = BeautifulSoup(self.session.get(url).text)
        link_el = soup.find("a", text="Ladda ner")
        link = urljoin(url, link_el.get("href"))
        self.log.info("%s: Downloading from %s" % (basefile,link))
        return self.download_if_needed(link, basefile)

    def fwdtests(self):
        t = super(SOSFS, self).fwdtests()
        t["dcterms:identifier"] = ['^([A-ZÅÄÖ-]+FS\s\s?\d{4}:\d+)'],
        return t

    def parse_metadata_from_textreader(self, reader, doc):
        # cue past the first cover pages until we find the first real page
        page = 1
        while "Ansvarig utgivare" not in reader.peekchunk('\f'):
            self.log.debug("%s: Skipping cover page %s" % (doc.basefile, page))
            reader.readpage()
            page += 1
        return super(SOSFS, self).parse_metadata_from_textreader(reader, doc)
    
class DVFS(MyndFskr):
    alias = "dvfs"
    start_url = "http://www.domstol.se/Ladda-ner--bestall/Verksamhetsstyrning/DVFS/DVFS1/"
    downloaded_suffix = ".html"

    nextpage_regex = ">"
    nextpage_url_regex = None
    basefile_regex = "^\s*(?P<basefile>\d{4}:\d+)"
    download_rewrite_url = True
    download_formid = "aspnetForm"

    def remote_url(self, basefile):
        return "http://www.domstol.se/Ladda-ner--bestall/Verksamhetsstyrning/DVFS/DVFS2/%s/" % basefile.replace(":","")

    def download_post_form(self, form, url):
        # nexturl == "javascript:__doPostBack('ctl00$MainRegion$"
        #            "MainContentRegion$LeftContentRegion$ctl01$"
        #            "epiNewsList$ctl09$PagingID15','')"
        etgt, earg = [m.group(1) for m in re.finditer("'([^']*)'", url)]
        fields = dict(form.fields)

        # requests seem to prefer that keys and values to the
        # files argument should be str (eg bytes) on py2 and
        # str (eg unicode) on py3. But we use unicode_literals
        # for this file, so we define a wrapper to convert
        # unicode strs in the appropriate way
        if six.PY2:
            f = six.binary_type
        else:
            f = lambda x: x
        fields[f('__EVENTTARGET')] = etgt
        fields[f('__EVENTARGUMENT')] = earg
        for k, v in fields.items(): 
            if v is None:
                fields[k] = f('')
        # using the files argument to requests.post forces the
        # multipart/form-data encoding
        req = requests.Request(
            "POST", form.get("action"), cookies=self.session.cookies, files=fields).prepare()
        # Then we need to remove filename from req.body in an
        # unsupported manner in order not to upset the
        # sensitive server
        body = req.body
        if isinstance(body, bytes):
            body = body.decode() # should be pure ascii
        req.body = re.sub(
            '; filename="[\w\-\/]+"', '', body).encode()
        req.headers['Content-Length'] = str(len(req.body))
        # self.log.debug("posting to event %s" % etgt)
        resp = self.session.send(req, allow_redirects=True)
        return resp

    def textreader_from_basefile(self, basefile, encoding):
        infile = self.store.downloaded_path(basefile)
        soup = BeautifulSoup(util.readfile(infile))
        main = soup.find("div", id="readme")
        main.find("div", "rs_skip").decompose()
        maintext = main.get_text("\n\n", strip=True)
        outfile = self.store.path(basefile, 'intermediate', '.txt')
        util.writefile(outfile, maintext)
        return TextReader(string=maintext)

    def fwdtests(self):
        t = super(DVFS, self).fwdtests()
        t["dcterms:identifier"] = ['(DVFS\s\s?\d{4}:\d+)']
        return t
