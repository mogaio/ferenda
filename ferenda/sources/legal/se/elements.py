# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

from lxml.builder import ElementMaker

from ferenda.elements import (CompoundElement, OrdinalElement,
                              TemporalElement, UnicodeElement, Link,
                              Paragraph, Section, SectionalElement)

E = ElementMaker(namespace="http://www.w3.org/1999/xhtml")


class Forfattning(CompoundElement, TemporalElement):
    """Grundklass för en konsoliderad författningstext."""
    tagname = "body"
    classname = "konsolideradforfattning"

# Rubrik är en av de få byggstenarna som faktiskt inte kan innehålla
# något annat (det förekommer "aldrig" en hänvisning i en
# rubriktext). Den ärver alltså från UnicodeElement, inte
# CompoundElement.
class Rubrik(UnicodeElement, TemporalElement):
    """En rubrik av något slag - kan vara en huvud- eller underrubrik
    i löptexten, en kapitelrubrik, eller något annat"""

    def _get_tagname(self):
        if hasattr(self, 'type') and self.type == "underrubrik":
            return "h3"
        else:
            return "h2"
    tagname = property(_get_tagname, "Docstring here")

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Rubrik, self).__init__(*args, **kwargs)


class Stycke(CompoundElement):
    fragment_label = "S"
    tagname = "p"
    typeof = "rinfoex:Stycke"  # not defined by the rpubl vocab

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Stycke, self).__init__(*args, **kwargs)


class Strecksatslista (CompoundElement):
    tagname = "ul"
    classname = "strecksatslista"


class NumreradLista (CompoundElement):
    tagname = "ol"  # list elements have their ordinals encoded as rinfoex:punkt triples
    classname = "numreradlista"


class Bokstavslista (CompoundElement):
    tagname = "ol"
    classname = "bokstavslista"


class Tabell(CompoundElement):
    tagname = "table"


class Tabellrad(CompoundElement, TemporalElement):
    tagname = "tr"


class Tabellcell(CompoundElement):
    tagname = "td"


class Avdelning(CompoundElement, OrdinalElement):
    tagname = "div"
    fragment_label = "A"
    typeof = "rinfoex:Avdelning"
    
    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Avdelning, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        # parent_uri will be eg https://lagen.nu/1998:808, while uri
        # will be https://lagen.nu/1998:808/konsolidering/2015:670 --
        # it's better to use parent_uri as the base uri at this point
        res = super(Avdelning, self).as_xhtml(parent_uri, parent_uri)
        attrs = {}
        if self.underrubrik:
            res.insert(0, E('h2', self.underrubrik))
            # FIXME: attr is not a valid attribute of h1
            attrs['abbr'] = self.ordinal + ". " + self.underrubrik
        elif self.rubrik.startswith("AVDELNING "):
            # transform "AVDELNING I. INNEHÅLL, TILLÄMPNING OCH
            # DEFINITIONER" to "I. Innehåll, tillämpning och
            # definitioner" 
            segments = self.rubrik.split(". ", 1)
            segments[0] = segments[0].replace("AVDELNING ", "")
            segments[1] = segments[1].capitalize()
            attrs['abbr'] = ". ".join(segments)

        elif self.rubrik.startswith("AVD. "):
            # transform "AVD. C FÖRMÅNER VID SJUKDOM ELLER
            # ARBETSSKADA" to "C. Förmåner vid sjukdom eller
            # arbetsskada"            
            tmp = self.rubrik.replace("AVD. ", "")
            segments = [x.strip() for x in tmp.split(" ", 1)]
            segments[0] = segments[0].replace("AVD. ", "")
            if segments[0].endswith("."):  # Handle "AVD. VI. Särskilda bestämmelser ..." (2009:400)
                segments[0] = segments[0][:-1]
            segments[1] = segments[1].capitalize()
            attrs['abbr'] = ". ".join(segments)

        res.attrib.update({"property": "rinfoex:avdelningsnummer",
                           "content": self.ordinal})
        res.insert(0, E('h1', self.rubrik, attrs))
        return res

class Underavdelning(CompoundElement, OrdinalElement):
    # only ever used by SFB (2010:110)
    tagname = "div"
    fragment_label = "U"
    classname = "underavdelning"
    # No typeof defined, these arent really real entities (but they
    # need ids because of document navmenu

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Underavdelning, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        res = super(Underavdelning, self).as_xhtml()
        res.insert(0, E('h1', self.ordinal + " " + self.rubrik))
        return res

class UpphavtKapitel(UnicodeElement, OrdinalElement):
    """Ett UpphavtKapitel är annorlunda från ett upphävt Kapitel på så
    sätt att inget av den egentliga lagtexten finns kvar, bara en
    platshållare"""


class Kapitel(CompoundElement, OrdinalElement):
    fragment_label = "K"
    tagname = "div"
    typeof = "rpubl:Kapitel"  # FIXME: This is qname string, not
    # rdflib.URIRef (which would be better), since as_xhtml doesn't
    # have access to a graph with namespace bindings, which is
    # required to turn a URIRef to a qname
    
    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Kapitel, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        res = super(Kapitel, self).as_xhtml(uri, uri)
        res.attrib.update({"property": "rpubl:kapitelnummer",
                           "content": self.ordinal})
        res.insert(0, E('h1', self.rubrik))
        return res


class UpphavdParagraf(UnicodeElement, OrdinalElement):
    tagname = "div"
    classname = "upphavdparagraf"


class UpphavtKapitel(UnicodeElement, OrdinalElement):
    tagname = "div"
    classname = "upphavtkapitel"


# en paragraf har inget "eget" värde, bara ett nummer och ett eller
# flera stycken
class Paragraf(CompoundElement, OrdinalElement):
    fragment_label = "P"
    tagname = "div"
    typeof = "rpubl:Paragraf"  # FIXME: see above

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Paragraf, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        res = super(Paragraf, self).as_xhtml(uri, parent_uri)
        res.attrib.update({"property": "rpubl:paragrafnummer",
                           "content": self.ordinal})
        # NOTE: we insert the paragrafbeteckning within the first
        # stycke (res[0] is a dcterms:isPartOf <span>, res[1] is the
        # first Stycke). This makes XSLT rendering easier and is
        # probably not semantically incorrect.
        idx = 1 if len(res) > 1 else 0
        res[idx].insert(0, E('span', {'class': 'paragrafbeteckning'}, self.ordinal + " §"))
        return res



# kan innehålla nästlade numrerade listor
class Listelement(CompoundElement, OrdinalElement):
    fragment_label = "N"
    tagname = "li"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Listelement, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        res = super(Listelement, self).as_xhtml(uri, parent_uri)
        res.attrib.update({"property": "rinfoex:punkt",
                           "content": self.ordinal})
        return res
        

class Overgangsbestammelser(CompoundElement):

    def __init__(self, *args, **kwargs):
        self.rubrik = kwargs.get('rubrik', 'Övergångsbestämmelser')
        super(Overgangsbestammelser, self).__init__(*args, **kwargs)


class Overgangsbestammelse(CompoundElement, OrdinalElement):
    tagname = "div"
    classname = "overgangsbestammelse"
    fragment_label = "L"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Overgangsbestammelse, self).__init__(*args, **kwargs)


    def as_xhtml(self, uri=None, parent_uri=None):
        res = super(Overgangsbestammelse, self).as_xhtml(uri, parent_uri)
        return res
        

class Bilaga(CompoundElement):
    fragment_label = "B"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Bilaga, self).__init__(*args, **kwargs)


class Register(CompoundElement):
    """Innehåller lite metadata om en grundförfattning och dess
    efterföljande ändringsförfattningar"""
    tagname = "div"
    classname = "register"

    def __init__(self, *args, **kwargs):
        self.rubrik = kwargs.get('rubrik', None)
        super(Register, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        res = super(Register, self).as_xhtml()
        res.insert(0, E('h1', self.rubrik))
        return res


class Registerpost(CompoundElement):

    """Metadata for a particular Grundforfattning or Andringsforfattning in the form of a rdflib graph, optionally with a Overgangsbestammelse."""
    tagname = "div"
    classname = "registerpost"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Registerpost, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        # FIXME: Render this better (particularly the rpubl:andring
        # property -- should be parsed and linked)
        res = super(Registerpost, self).as_xhtml()
        # Bootstrap scrollspy has issues with using ':' (amongst other
        # chars) in a fragment. '-' is fine.
        res.set("id", res.get("id").replace(":", "-"))
        return res

class OrderedParagraph(Paragraph, OrdinalElement):

    def as_xhtml(self, baseuri, parent_uri=None):
        element = super(OrderedParagraph, self).as_xhtml(baseuri, parent_uri)
        # FIXME: id needs to be unique in document by prepending a
        # instans identifier
        # element.set('id', self.ordinal)
        return element


class DomElement(CompoundElement):
    tagname = "div"
    prop = None

    def _get_classname(self):
        return self.__class__.__name__.lower()
    classname = property(_get_classname)

    def as_xhtml(self, baseuri, parent_uri=None):
        element = super(DomElement, self).as_xhtml(baseuri, parent_uri)
        if self.prop:
            # ie if self.prop = ('ordinal', 'dcterms:identifier'), then
            # dcterms:identifier = self.ordinal
            if (hasattr(self, self.prop[0]) and
                    getattr(self, self.prop[0]) and
                    isinstance(getattr(self, self.prop[0]), str)):
                element.set('content', getattr(self, self.prop[0]))
                element.set('property', self.prop[1])
        return element


class Delmal(DomElement):
    uri = None
    prop = ('ordinal', 'rinfoex:delmalordinal')
    pass

class Instans(DomElement):
    uri = None
    prop = ('court', 'dcterms:creator')


class Dom(DomElement):
    prop = ('malnr', 'dcterms:identifier')


class Domskal(DomElement):
    pass


class Domslut(DomElement):
    pass  # dcterms:author <- names of judges


class Betankande(DomElement):
    pass  # dcterms:author <- referent


class Skiljaktig(DomElement):
    pass  # dcterms:author <- name


class Tillagg(DomElement):
    pass  # dcterms:author <- name


class Endmeta(DomElement):
    pass

class AnonSektion(CompoundElement):
    tagname = "div"

class Abstract(CompoundElement):
    tagname = "div"
    classname = "beslutikorthet"


class Blockquote(CompoundElement):
    tagname = "blockquote"


class Meta(CompoundElement):
    pass



class AnonStycke(Paragraph):
    pass


class Sektion(Section):
    pass

class VerbatimSection(CompoundElement):
    tagname = "div"
    classname = "verbatim"

class Sidbrytning(OrdinalElement):
    def as_xhtml(self, uri, parent_uri=None):
        attrs = {'id': 'sid%s' % self.ordinal,
                 'class': 'sidbrytning'}
        if hasattr(self, 'src') and self.src:
            attrs['src'] = self.src
            attrs['width'] = str(self.width)
            attrs['height'] = str(self.height)
        
        return E("span", attrs)
    def as_plaintext(self):
        return "\n\n"

class PreambleSection(CompoundElement):
    tagname = "div"
    classname = "preamblesection"
    counter = 0
    uri = None

    def as_xhtml(self, uri, parent_uri=None):
        if not self.uri:
            self.__class__.counter += 1
            self.uri = uri + "#PS%s" % self.__class__.counter
        element = super(PreambleSection, self).as_xhtml(uri, parent_uri)
        element.set('property', 'dcterms:title')
        element.set('content', self.title)
        element.set('typeof', 'bibo:DocumentPart')
        return element


class PseudoSection(CompoundElement):
    # used when we really want to use a Section, but can't since we
    # don't have an ordinal (or the ordinal is invalid/duplicate)
    tagname = "div"
    classname = "pseudosection"

    def as_xhtml(self, uri, parent_uri=None):
        element = super(PseudoSection, self).as_xhtml(uri, parent_uri)
        # do not add @property='dcterms:title' as we don't want to
        # create a RDF triple out of this
        element.set('content', self.title)
        return element
    


class UnorderedSection(CompoundElement):
    # FIXME: It'd be nice with some way of ordering nested unordered
    # sections, like:
    #  US1
    #  US2
    #    US2.1
    #    US2.2
    #  US3
    #
    # right now they'll appear as:
    #  US1
    #  US2
    #    US3
    #    US4
    #  US5
    tagname = "div"
    classname = "unorderedsection"
    counter = 0
    uri = None

    def as_xhtml(self, uri, parent_uri=None):
        if not self.uri:
            self.__class__.counter += 1
            # note that this becomes a document-global running counter
            self.uri = uri + "#US%s" % self.__class__.counter
        element = super(UnorderedSection, self).as_xhtml(uri, parent_uri)
        element.set('property', 'dcterms:title')
        element.set('content', self.title)
        element.set('typeof', 'bibo:DocumentPart')
        return element


class Forfattningskommentar(CompoundElement):
    tagname = "div"
    classname = "forfattningskommentar"
    
    def as_xhtml(self, uri, parent_uri=None):
        if not self.uri and self.comment_on:
            # FIXME: this will normally create fragments with
            # extra fragments, ie
            # 'https://lagen.nu/prop/2013/14:34#2010:1846#P52' --
            # is that even legal?
            self.uri = uri + "#kommentar-" + self.comment_on.rsplit("/")[-1]
        element = super(Forfattningskommentar, self).as_xhtml(uri, parent_uri)
        element.set("typeof", "rinfoex:Forfattningskommentar")
        if self.comment_on:
            span = E("span", {"rel": "rinfoex:kommentarTill",
                              "href": self.comment_on})
            div = E("div")
            for child in list(element):
                if child.tag != "{http://www.w3.org/1999/xhtml}span" or not child.get("rel"):
                    element.remove(child)
                    # remove attribs that don't need to be in the RDF
                    if child.get("class"):
                        del child.attrib["class"]
                    if child.get("style"):
                        del child.attrib["style"]
                    div.append(child)
            assert len(div) > 0, "Författningskommentar for %s seems empty" % self.uri
            element.append(span)
            if hasattr(self, 'label'):
                element.append(E("span", {"property": "rdfs:label",
                                          "content": self.label}))
            # also wrap everything* in a <div about="{comment_on}
            # property="dcterms:description"
            # datatype="rdf:XMLLiteral">
            element.append(E("div", div, {'property': 'dcterms:description',
                                          'datatype':'rdf:XMLLiteral'}))
            
        if hasattr(self, "title"):
            element.set("content", self.title)
        
        return element

class Appendix(SectionalElement):
    tagname = "div"
    classname = "appendix"

    def as_xhtml(self, uri, parent_uri=None):
        if not self.uri:
            self.uri = uri + "#B%s" % self.ordinal

        return super(Appendix, self).as_xhtml(uri, parent_uri)


# in older propositioner, the document is typically structured as
# PreambleSection("Propositionens huvudsakliga innehåll")
# PreambleSection("Propositionens lagförslag")
# ProtokollsUtdrag("Justitiedepartementet")
#   Section("1 Inledning")
#   Section("2 Allmän motivering")
#     Section("2.1 Allmänna utgångspunkter")
#  ...
# ProtokollsUtdrag("Lagrådet")
# ProtokollsUtdrag("Justitiedepartementet")
#
# meaning this is three protocol excerpts after another: the first
# (the main one) being the proposition to lagrådet, the second
# (shorter) being lagrådets suggestions on the given prop, and the
# third (very short, mostly formal) is amendments to the first prop,
# after taking lagrådets suggestions into account. The third might be
# divided into sections, but we should take care not to mint URIs for
# them as they'll clash with sections in the first. 
class Protokollsutdrag(CompoundElement):
    tagname = "div"
    classname = "protokollsutdrag"
    def as_xhtml(self, uri, parent_uri=None):
        element = super(Protokollsutdrag, self).as_xhtml(uri, parent_uri)
        # do not add @property='dcterms:title' as we don't want to
        # create a RDF triple out of this
        element.set('content', self.title)
        return element

# FIXME: This ought to be not needed anymore now that we use
# PDFAnalyzer to segment pdfs into subdocs (the coverpages should be a
# separate document apart from main)
class Coverpage(CompoundElement):
    tagname = "div"
    classname = "coverpage"


class DokumentRubrik(UnicodeElement):
    tagname = "h1"
    

class PropHuvudrubrik(DokumentRubrik):
    # this is always something like "Regeringens proposition 2005/06:173"
    classname = "prophuvudrubrik"

    
class PropRubrik(DokumentRubrik):
    # This is the actual dcterms:title of the document
    classname = "proprubrik"
    # FIXME: make it output a dcterms:title triple?


class FrontmatterSection(CompoundElement):
    # used for the first few headers (PropHuvudrubrik, PropRubrik) and
    # lines in a proposition
    tagname = "div"
    classname = "frontmatter"
    
