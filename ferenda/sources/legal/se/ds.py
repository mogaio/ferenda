# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

import re
import logging
from collections import OrderedDict, Counter

from rdflib.namespace import SKOS
from cached_property import cached_property

from ferenda import PDFAnalyzer
from ferenda.errors import ParseError
from . import Regeringen, Offtryck, RPUBL 


class DsAnalyzer(PDFAnalyzer):
    # NOTE: The cutoff used to be 0.5% but it turns out that in
    # particular h2's can be quite rare, occuring maybe two times
    # in an entire document.
    style_significance_threshold = 0.001

    @cached_property
    def documents(self):
        def titleish(page):
            for textelement in page:
                if textelement.font.size >= 18: # Ds 2009:55 uses size 18. The normal is 26.
                    return textelement
        documents = []
        mainstyles = Counter()
        currentdoc = 'frontmatter'
        for pageidx, page in enumerate(self.pdf):
            # Sanity check: 
            if pageidx > 5 and currentdoc == 'frontmatter':
                logging.getLogger("pdfanalyze").warn("missed the transition from frontmatter to main")
                # act as there never was any frontmatter
                currentdoc = "main"
                documents[0][-1] = "main"
            pgtitle = titleish(page)
            if pgtitle is not None:
                # The normal title indicating that the real content
                # starts is Innehåll, but eg Ds 2009:55 (which is
                # atypical) uses Innehållsförteckning.
                if str(pgtitle).strip() in ("Innehåll", "Innehållsförteckning"):
                    currentdoc = "main"
                elif re.match("Till \w+minister ", str(pgtitle).strip()):
                    currentdoc = "main"
                elif re.match("Departementsserien \d+", str(pgtitle).strip()):
                    currentdoc = 'endregister'
            styles = self.count_styles(pageidx, 1)
            # find the most dominant style on the page. If it uses the
            # EU font, it's a separate section.
            if styles and styles.most_common(1)[0][0][0].startswith("EUAlbertina"):
                currentdoc = 'eudok'
            elif currentdoc == "eudok":
                currentdoc == "main" ## CONTINUE
            if currentdoc == "main":
                mainstyles += styles
            # update the current document segment tuple or start a new one
            if documents and documents[-1][2] == currentdoc:
                documents[-1][1] += 1
            else:
                documents.append([pageidx, 1, currentdoc])
        return documents


# See SOU.py for discussion about possible other sources
class Ds(Regeringen):
    alias = "ds"
    re_basefile_strict = re.compile(r'Ds (\d{4}:\d+)')
    # Like with re_urlbasefile_*, we must insist on a leading Ds, or
    # else we'll match non-Ds documents which mentions SFS id, like
    # http://www.regeringen.se/rattsdokument/departementsserien-och-promemorior/2015/03/u20151807f/
    re_basefile_lax = re.compile(r'Ds ?(\d{4}:\d+)', re.IGNORECASE)
    # NB: We require that the last segment always starts with ds, to
    # avoid getting non-Ds-documents (eg
    # http://www.regeringen.se/rattsdokument/departementsserien-och-promemorior/2015/11/andring-av-en-avvisningsbestammelse-i-utlanningslagen-2005716/
    # which is not a Ds, but which a naive url regex classifies as Ds
    # 2005:716)
    re_urlbasefile_strict = re.compile("departementsserien-och-promemorior/\d+/\d+/ds-?(\d{4})(\d+)-?/$")
    re_urlbasefile_lax = re.compile("departementsserien-och-promemorior/\d+/\d+/ds-?(\d{4})_?(\d+)")
    rdf_type = RPUBL.Utredningsbetankande
    document_type = Regeringen.DS
    urispace_segment = "utr/ds"

    # NB: The same logic as in
    # ferenda.sources.legal.se.{Regeringen,Riksdagen}.metadata_from_basefile
    def metadata_from_basefile(self, basefile):
        a = super(Ds, self).metadata_from_basefile(basefile)
        a["rpubl:arsutgava"], a["rpubl:lopnummer"] = basefile.split(":", 1)
        a["rpubl:utrSerie"] = self.lookup_resource("Ds", SKOS.altLabel)
        return a
