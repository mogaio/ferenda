# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
"""This module finds references to legal sources (including individual
sections, eg 'Upphovsrättslag (1960:729) 49 a §') in plaintext"""

import sys
import os
import re
import hashlib
import logging
import tempfile
import shutil
# 3rdparty libs

from six import unichr as chr

# needed early
from ferenda import util

external_simpleparse_state = None
try:
    from simpleparse.parser import Parser
    from simpleparse.stt.TextTools.TextTools import tag
except ImportError:
    # Mimic the simpleparse interface (the very few parts we're using)
    # but call external python 2.7 processes behind the scene.

    # external_simpleparse_state = "simpleparse.tmp"
    python_exe = os.environ.get("FERENDA_PYTHON2_FALLBACK",
                                "python2.7")

    def _setup_state():
        state = tempfile.mkdtemp()
        buildtagger_script = state + os.sep + "buildtagger.py"
        util.writefile(buildtagger_script, """import sys,os
if sys.version_info >= (3,0,0):
    raise OSError("This is python %s, not python 2.6 or 2.7!" % sys.version_info)
declaration = sys.argv[1] # md5 sum of the entire content of declaration
production = sys.argv[2]  # short production name
picklefile = "%s-%s.pickle" % (declaration, production)
from simpleparse.parser import Parser
from simpleparse.stt.TextTools.TextTools import tag
import cPickle as pickle

with open(declaration,"rb") as fp:
    p = Parser(fp.read(), production)
t = p.buildTagger(production)
with open(picklefile,"wb") as fp:
    pickle.dump(t,fp)""")

        tagstring_script = state + os.sep + "tagstring.py"
        util.writefile(tagstring_script, """import sys, os
if sys.version_info >= (3,0,0):
    raise OSError("This is python %s, not python 2.6 or 2.7!" % sys.version_info)
pickled_tagger = sys.argv[1] # what buildtagger.py returned -- full path
full_text_path = sys.argv[2]
text_checksum = sys.argv[3] # md5 sum of text, just the filename
picklefile = "%s-%s.pickle" % (pickled_tagger, text_checksum)

from simpleparse.stt.TextTools.TextTools import tag

import cPickle as pickle

with open(pickled_tagger) as fp:
    t = pickle.load(fp)
with open(full_text_path, "rb") as fp:
    text = fp.read()
tagged = tag(text, t, 0, len(text))
with open(picklefile,"wb") as fp:
    pickle.dump(tagged,fp)
        """)
        return state

    # print("(__boot__): calling _setup_state to setup external_simpleparse_state")
    external_simpleparse_state = _setup_state()

    class Parser(object):

        def __init__(self, declaration, root='root', prebuilts=(), definitionSources=[]):
            global external_simpleparse_state
            # 2. dump declaration to a tmpfile read by the script
            c = hashlib.md5()
            c.update(declaration)
            self.declaration_md5 = c.hexdigest()
            if not external_simpleparse_state:
                # print("__init__: calling _setup_state to setup external_simpleparse_state")
                external_simpleparse_state = _setup_state()
            declaration_filename = "%s/%s" % (external_simpleparse_state,
                                              self.declaration_md5)
            with open(declaration_filename, "wb") as fp:
                fp.write(declaration)

        def __del__(self):
            global external_simpleparse_state
            if external_simpleparse_state and os.path.exists(external_simpleparse_state):
                shutil.rmtree(external_simpleparse_state)
                # print("__del__: setting external_simpleparse_state to None")
                external_simpleparse_state = None

        def buildTagger(self, production=None, processor=None):
            pickled_tagger = "%s/%s-%s.pickle" % (external_simpleparse_state,
                                                  self.declaration_md5,
                                                  production)
            if not os.path.exists(pickled_tagger):

                #    3. call the script with python 27 and production
                cmdline = "%s %s %s/%s %s" % (python_exe,
                                              external_simpleparse_state +
                                              os.sep + "buildtagger.py",
                                              external_simpleparse_state,
                                              self.declaration_md5,
                                              production)
                util.runcmd(cmdline, require_success=True)
                #    4. the script builds tagtable and dumps it to a pickle file
                assert os.path.exists(pickled_tagger)
            return pickled_tagger  # filename instead of tagtable struct

    def tag(text, tagtable, sliceleft, sliceright):
        global external_simpleparse_state
        # print("tag: external_simpleparse_state is %s" % external_simpleparse_state)
        if external_simpleparse_state is None:
            external_simpleparse_state = _setup_state()
        c = hashlib.md5()
        c.update(text)
        text_checksum = c.hexdigest()
        pickled_tagger = tagtable  # remember, not a real tagtable struct
        pickled_tagged = "%s-%s.pickle" % (pickled_tagger, text_checksum)

        if not os.path.exists(pickled_tagged):
            # 2. Dump text as string
            full_text_path = "%s/%s.txt" % (os.path.dirname(pickled_tagger),
                                            text_checksum)
            util.ensure_dir(full_text_path)
            with open(full_text_path, "wb") as fp:
                fp.write(text)
                # 3. call script (that loads the pickled tagtable + string
                # file, saves tagged text as pickle)
            util.runcmd("%s %s %s %s %s" %
                        (python_exe,
                         external_simpleparse_state + os.sep + "tagstring.py",
                         pickled_tagger,
                         full_text_path,
                         text_checksum),
                        require_success=True)
        # 4. load tagged text pickle
        with open(pickled_tagged, "rb") as fp:
            res = pickle.load(fp)
        return res


import six
from six.moves import cPickle as pickle
from six import text_type as str

from rdflib import Graph, Namespace, Literal, BNode, RDFS, RDF
COIN = Namespace("http://purl.org/court/def/2009/coin#")

# my own libraries

from ferenda.elements import Link
from ferenda.elements import LinkSubject
from ferenda.thirdparty.coin import URIMinter
from . import RPUBL

# The charset used for the bytestrings that is sent to/from
# simpleparse (which does not handle unicode)
# Choosing utf-8 makes § a two-byte character, which does not work well
SP_CHARSET = 'iso-8859-1'

log = logging.getLogger('lr')


class NodeTree:

    """Encapsuates the node structure from mx.TextTools in a tree oriented interface"""

    def __init__(self, root, data, offset=0, isRoot=True):
        self.data = data
        self.root = root
        self.isRoot = isRoot
        self.offset = offset

    def __getattr__(self, name):
        if name == "text":
            return self.data.decode(SP_CHARSET)
        elif name == "tag":
            return (self.isRoot and 'root' or self.root[0])
        elif name == "nodes":
            res = []
            l = (self.isRoot and self.root[1] or self.root[3])
            if l:
                for p in l:
                    res.append(NodeTree(p, self.data[p[1] -
                                                     self.offset:p[2] - self.offset], p[1], False))
            return res
        else:
            raise AttributeError


class RefParseError(Exception):
    pass

# Lite om hur det hela funkar: Att hitta referenser i löptext är en
# tvåstegsprocess.
#
# I det första steget skapar simpleparse en nodstruktur från indata
# och en lämplig ebnf-grammatik. Väldigt lite kod i den här modulen
# hanterar första steget, simpleparse gör det tunga
# jobbet. Nodstrukturen kommer ha noder med samma namn som de
# produktioner som definerats i ebnf-grammatiken.
#
# I andra steget gås nodstrukturen igenom och omvandlas till en lista
# av omväxlande unicode- och Link-objekt. Att skapa Link-objekten är
# det svåra, och det mesta jobbet görs av formatter_dispatch. Den
# tittar på varje nod och försöker hitta ett lämpligt sätt att
# formattera den till ett Link-objekt med en uri-property. Eftersom
# vissa produktioner ska resultera i flera länkar och vissa bara i en
# kan detta inte göras av en enda formatteringsfunktion. För de enkla
# fallen räcker den generiska formatteraren format_tokentree till, men
# för svårare fall skrivs separata formatteringsfunktioner. Dessa har
# namn som matchar produktionerna (exv motsvaras produktionen
# ChapterSectionRefs av funktionen format_ChapterSectionRefs).
#
# Koden är tänkt att vara generell för all sorts referensigenkänning i
# juridisk text. Eftersom den växt från kod som bara hanterade rena
# lagrumsreferenser är det ganska mycket kod som bara är relevant för
# igenkänning av just svenska lagrumsänvisningar så som de förekommer
# i SFS. Sådana funktioner/avsnitt är markerat med "SFS-specifik
# [...]" eller "KOD FÖR LAGRUM"


class LegalRef:
    # Kanske detta borde vara 1,2,4,8 osv, så att anroparen kan be om
    # LAGRUM | FORESKRIFTER, och så vi kan definera samlingar av
    # vanliga kombinationer (exv ALL_LAGSTIFTNING = LAGRUM |
    # KORTLAGRUM | FORESKRIFTER | EULAGSTIFTNING)
    LAGRUM = 1             # hänvisningar till lagrum i SFS
    KORTLAGRUM = 2         # SFS-hänvisningar på kortform
    FORESKRIFTER = 3       # hänvisningar till myndigheters författningssamlingar
    EULAGSTIFTNING = 4     # EU-fördrag, förordningar och direktiv
    INTLLAGSTIFTNING = 5   # Fördrag, traktat etc
    FORARBETEN = 6         # proppar, betänkanden, etc
    RATTSFALL = 7          # Rättsfall i svenska domstolar
    MYNDIGHETSBESLUT = 8   # Myndighetsbeslut (JO, ARN, DI...)
    EURATTSFALL = 9        # Rättsfall i EG-domstolen/förstainstansrätten
    INTLRATTSFALL = 10     # Europadomstolen
    DOMSTOLSAVGORANDEN = 11# Underliggande beslut i ett rättsfallsreferat

    # re_urisegments = re.compile(r'([\w]+://[^/]+/[^\d]*)(\d+:(bih\.
    # |N|)?\d+( s\.\d+|))#?(K(\d+)|)(P(\d+)|)(S(\d+)|)(N(\d+)|)')
    re_urisegments = re.compile(
        r'([\w]+://[^/]+/[^\d]*)(\d+:(bih\.[_ ]|N|)?\d+([_ ]s\.\d+|))#?(K([a-z0-9]+)|)(P([a-z0-9]+)|)(S(\d+)|)(N(\d+)|)')
    re_escape_compound = re.compile(
        r'\b(\w+-) (och) (\w+-?)(lagen|förordningen)\b', re.UNICODE)
    re_escape_named = re.compile(
        r'\B(lagens?|balkens?|förordningens?|formens?|ordningens?|kungörelsens?|stadgans?)\b', re.UNICODE)

    re_descape_compound = re.compile(
        r'\b(\w+-)_(och)_(\w+-?)(lagen|förordningen)\b', re.UNICODE)
    re_descape_named = re.compile(
        r'\|(lagens?|balkens?|förordningens?|formens?|ordningens?|kungörelsens?|stadgans?)')
    re_xmlcharref = re.compile("&#\d+;")

    def __init__(self, *args):
        # FIXME: We'd like to make the EBNF/N3 loading parts use 
        # ResourceLoader instead of hardcoded paths
        if not os.path.sep in __file__:
            scriptdir = os.getcwd()
        else:
            scriptdir = os.path.dirname(__file__)

        self.graph = Graph()
        n3file = os.path.relpath(scriptdir + "/res/extra/sfs.ttl")
        # print "loading n3file %s" % n3file
        self.graph.load(n3file, format="n3")
        self.roots = []
        self.uriformatter = {}
        self.decl = ""  # try to make it unicode clean all the way
        self.namedlaws = {}
        self.load_ebnf(scriptdir + "/res/ebnf/base.ebnf")

        self.args = args
        if self.LAGRUM in args:
            productions = self.load_ebnf(scriptdir + "/res/ebnf/lagrum.ebnf")
            for p in productions:
                self.uriformatter[p] = self.sfs_format_uri
            self.namedlaws.update(self.get_relations(RDFS.label))
            self.roots.append("sfsrefs")
            self.roots.append("sfsref")

        if self.KORTLAGRUM in args:
            # om vi inte redan laddat lagrum.ebnf måste vi göra det
            # nu, eftersom kortlagrum.ebnf beror på produktioner som
            # definerats där
            if not self.LAGRUM in args:
                self.load_ebnf(scriptdir + "/res/ebnf/lagrum.ebnf")

            productions = self.load_ebnf(
                scriptdir + "/res/ebnf/kortlagrum.ebnf")
            for p in productions:
                self.uriformatter[p] = self.sfs_format_uri
            DCTERMS = Namespace("http://purl.org/dc/terms/")
            d = self.get_relations(DCTERMS['alternate'])
            self.namedlaws.update(d)
            # lawlist = [x.encode(SP_CHARSET) for x in list(d.keys())]
            lawlist = list(d.keys())
            # Make sure longer law abbreviations come before shorter
            # ones (so that we don't mistake "3 § MBL" for "3 § MB"+"L")
            # lawlist.sort(cmp=lambda x, y: len(y) - len(x))
            lawlist.sort(key=len, reverse=True)
            lawdecl = "LawAbbreviation ::= ('%s')\n" % "'/'".join(lawlist)
            self.decl += lawdecl
            self.roots.insert(0, "kortlagrumref")

        if self.EULAGSTIFTNING in args:
            productions = self.load_ebnf(scriptdir + "/res/ebnf/eglag.ebnf")
            for p in productions:
                self.uriformatter[p] = self.eglag_format_uri
            self.roots.append("eglagref")
        if self.FORARBETEN in args:
            productions = self.load_ebnf(
                scriptdir + "/res/ebnf/forarbeten.ebnf")
            for p in productions:
                self.uriformatter[p] = self.forarbete_format_uri
            self.roots.append("forarbeteref")
        if self.RATTSFALL in args:
            productions = self.load_ebnf(scriptdir + "/res/ebnf/rattsfall.ebnf")
            for p in productions:
                self.uriformatter[p] = self.rattsfall_format_uri
            self.roots.append("rattsfallref")
        if self.EURATTSFALL in args:
            productions = self.load_ebnf(scriptdir + "/res/ebnf/egratt.ebnf")
            for p in productions:
                self.uriformatter[p] = self.egrattsfall_format_uri
            self.roots.append("ecjcaseref")

        rootprod = "root ::= (%s/plain)+\n" % "/".join(self.roots)
        self.decl += rootprod

        self.parser = Parser(self.decl.encode(SP_CHARSET), "root")
        self.tagger = self.parser.buildTagger("root")
        # util.writefile("tagger.tmp", repr(self.tagger), SP_CHARSET)
        # print "tagger length: %d" % len(repr(self.tagger))
        self.verbose = False
        self.depth = 0

        # SFS-specifik kod
        self.currentlaw = None
        self.currentchapter = None
        self.currentsection = None
        self.currentpiece = None
        self.lastlaw = None
        self.currentlynamedlaws = {}

    def load_ebnf(self, file):
        """Laddar in produktionerna i den angivna filen i den
        EBNF-deklaration som används, samt returnerar alla
        *Ref och *RefId-produktioner"""
        # base.ebnf contains 0x1A, ie the EOF character on windows,
        # therefore we need to read it in binary mode

        f = open(file, 'rb')
        # assume our ebnf files use the same charset
        content = f.read(os.stat(file).st_size).decode(SP_CHARSET)
        self.decl += content
        f.close()
        return [x.group(1) for x in re.finditer(r'(\w+(Ref|RefID))\s*::=', content)]

    def get_relations(self, predicate):
        d = {}
        for obj, subj in self.graph.subject_objects(predicate):
            d[six.text_type(subj)] = six.text_type(obj)
        return d

    def parse(self, 
              indata,
              minter,
              baseuri_attributes=None,
              predicate=None,
              allow_relative=True):
        assert isinstance(indata, str)
        assert isinstance(minter, URIMinter)
        if indata == "":
            return indata  # this actually triggered a bug...
        self.predicate = predicate
        self.minter = minter
        self.allow_relative = allow_relative
        if baseuri_attributes:
            # Might contain 'baseuri', 'law', 'chapter', 'section', 'piece', 'item'
            self.baseuri_attributes = baseuri_attributes
        else:
            self.baseuri_attributes = {"law": "9999:999",
                                       "chapter": "9",
                                       "section": "9",
                                       "piece": "9",
                                       "items": "9"}

        # Det är svårt att få EBNF-grammatiken att känna igen
        # godtyckliga ord som slutar på ett givet suffix (exv
        # 'bokföringslagen' med suffixet 'lagen'). Därför förbehandlar
        # vi indatasträngen och stoppar in ett '|'-tecken innan vissa
        # suffix. Vi transformerar även 'Radio- och TV-lagen' till
        # 'Radio-_och_TV-lagen'
        fixedindata = indata  # FIXME: Nonsensical
        if self.LAGRUM in self.args:
            fixedindata = self.re_escape_compound.sub(
                r'\1_\2_\3\4', fixedindata)
            fixedindata = self.re_escape_named.sub(r'|\1', fixedindata)
        # print "After: %r" % type(fixedindata)

        # SimpleParse har inget stöd för unicodesträngar, så vi
        # konverterar intdatat till en bytesträng. Tyvärr får jag inte
        # det hela att funka med UTF8, så vi kör xml character
        # references istället
        fixedindata = fixedindata.encode(SP_CHARSET, 'xmlcharrefreplace')

        # Parsea texten med TextTools.tag - inte det enklaste sättet
        # att göra det, men om man gör enligt
        # Simpleparse-dokumentationen byggs taggertabellen om för
        # varje anrop till parse()
        if self.verbose:
            print(("calling tag with '%s'" % (fixedindata.decode(SP_CHARSET))))
        # print "tagger length: %d" % len(repr(self.tagger))
        taglist = tag(fixedindata, self.tagger, 0, len(fixedindata))

        result = []

        root = NodeTree(taglist, fixedindata)
        for part in root.nodes:
            if part.tag != 'plain' and self.verbose:
                sys.stdout.write(self.prettyprint(part))
            if part.tag in self.roots:
                self.clear_state()
                # self.verbose = False
                result.extend(self.formatter_dispatch(part))
            else:
                assert part.tag == 'plain', "Tag is %s" % part.tag
                result.append(part.text)

            # clear state
            if self.currentlaw is not None:
                self.lastlaw = self.currentlaw
            self.currentlaw = None

        if taglist[-1] != len(fixedindata):
            log.error('Problem (%d:%d) with %r / %r' % (
                taglist[-1] - 8, taglist[-1] + 8, fixedindata, indata))

            raise RefParseError(
                "parsed %s chars of %s (...%s...)" % (taglist[-1], len(indata),
                                                      indata[(taglist[-1] - 2):taglist[-1] + 3]))

        # Normalisera resultatet, dvs konkatenera intilliggande
        # textnoder, och ta bort ev '|'-tecken som vi stoppat in
        # tidigare.
        normres = []
        for i in range(len(result)):
            if not self.re_descape_named.search(result[i]):
                node = result[i]
            else:
                if self.LAGRUM in self.args:
                    text = self.re_descape_named.sub(r'\1', result[i])
                    text = self.re_descape_compound.sub(r'\1 \2 \3\4', text)
                if isinstance(result[i], Link):
                    # Eftersom Link-objekt är immutable måste vi skapa
                    # ett nytt och kopiera dess attribut
                    if hasattr(result[i], 'predicate'):
                        node = LinkSubject(text, predicate=result[i].predicate,
                                           uri=result[i].uri)
                    else:
                        node = Link(text, uri=result[i].uri)
                else:
                    node = text
            if (len(normres) > 0
                and not isinstance(normres[-1], Link)
                    and not isinstance(node, Link)):
                normres[-1] += node
            else:
                normres.append(node)

        # and finally...
        for i in range(len(normres)):
            if isinstance(normres[i], Link):
                # deal with these later
                pass
            else:
                normres[i] = self.re_xmlcharref.sub(
                    self.unescape_xmlcharref, normres[i])
        return normres

    def unescape_xmlcharref(self, m):
        return chr(int(m.group(0)[2:-1]))

    def find_attributes(self, parts, extra={}):
        """recurses through a parse tree and creates a dictionary of
        attributes"""
        d = {}

        self.depth += 1
        if self.verbose:
            print(
                (". " * self.depth + "find_attributes: starting with %s" % d))
        if extra:
            d.update(extra)

        for part in parts:
            current_part_tag = part.tag.lower()
            if current_part_tag.endswith('refid'):
                if ((current_part_tag == 'singlesectionrefid') or
                        (current_part_tag == 'lastsectionrefid')):
                    current_part_tag = 'sectionrefid'
                d[current_part_tag[:-5]] = part.text.strip()
                if self.verbose:
                    print((". " * self.depth +
                           "find_attributes: d is now %s" % d))

            if part.nodes:
                d.update(self.find_attributes(part.nodes, d))
        if self.verbose:
            print((". " * self.depth + "find_attributes: returning %s" % d))
        self.depth -= 1

        if self.currentlaw and 'law' not in d:
            d['law'] = self.currentlaw
        if self.currentchapter and 'chapter' not in d:
            d['chapter'] = self.currentchapter
        if self.currentsection and 'section' not in d:
            d['section'] = self.currentsection
        if self.currentpiece and 'piece' not in d:
            d['piece'] = self.currentpiece

        return d

    def find_node(self, root, nodetag):
        """Returns the first node in the tree that has a tag matching nodetag. The search is depth-first"""
        if root.tag == nodetag:  # base case
            return root
        else:
            for node in root.nodes:
                x = self.find_node(node, nodetag)
                if x is not None:
                    return x
            return None

    def find_nodes(self, root, nodetag):
        if root.tag == nodetag:
            return [root]
        else:
            res = []
            for node in root.nodes:
                res.extend(self.find_nodes(node, nodetag))
            return res

    def flatten_tokentree(self, part, suffix):
        """returns a 'flattened' tokentree ie for the following tree and the suffix 'RefID'
           foo->bar->BlahongaRefID
              ->baz->quux->Blahonga2RefID
                         ->Blahonga3RefID
              ->Blahonga4RefID

           this should return [BlahongaRefID, Blahonga2RefID, Blahonga3RefID, Blahonga4RefID]"""
        l = []
        if part.tag.endswith(suffix):
            l.append(part)
        if not part.nodes:
            return l

        for subpart in part.nodes:
            l.extend(self.flatten_tokentree(subpart, suffix))
        return l

    def formatter_dispatch(self, part):
        # print "Verbositiy: %r" % self.verbose
        self.depth += 1
        # Finns det en skräddarsydd formatterare?
        if "format_" + part.tag in dir(self):
            formatter = getattr(self, "format_" + part.tag)
            if self.verbose:
                print(
                    ((". " * self.depth) + "formatter_dispatch: format_%s defined, calling it" % part.tag))
            res = formatter(part)
            assert res is not None, "Custom formatter for %s didn't return anything" % part.tag
        else:
            if self.verbose:
                print(
                    ((". " * self.depth) + "formatter_dispatch: no format_%s, using format_tokentree" % part.tag))
            res = self.format_tokentree(part)

        if res is None:
            print(((". " * self.depth) +
                   "something wrong with this:\n" + self.prettyprint(part)))
        self.depth -= 1
        return res

    def format_tokentree(self, part):
        # This is the default formatter. It converts every token that
        # ends with a RefID into a Link object. For grammar
        # productions like SectionPieceRefs, which contain
        # subproductions that also end in RefID, this is not a good
        # function to use - use a custom formatter instead.

        res = []

        if self.verbose:
            print(((". " * self.depth) +
                   "format_tokentree: called for %s" % part.tag))
        # this is like the bottom case, or something
        if (not part.nodes) and (not part.tag.endswith("RefID")):
            res.append(part.text)
        else:
            if part.tag.endswith("RefID"):
                res.append(self.format_generic_link(part))
            elif part.tag.endswith("Ref"):
                res.append(self.format_generic_link(part))
            else:
                for subpart in part.nodes:
                    if self.verbose and part.tag == 'LawRef':
                        print(
                            ((". " * self.depth) + "format_tokentree: part '%s' is a %s" % (subpart.text, subpart.tag)))
                    res.extend(self.formatter_dispatch(subpart))
        if self.verbose:
            print(
                ((". " * self.depth) + "format_tokentree: returning '%s' for %s" % (res, part.tag)))
        return res

    def prettyprint(self, root, indent=0):
        res = "%s'%s': '%s'\n" % (
            "    " * indent, root.tag, re.sub(r'\s+', ' ', root.text))
        if root.nodes is not None:
            for subpart in root.nodes:
                res += self.prettyprint(subpart, indent + 1)
            return res
        else:
            return ""

    def format_generic_link(self, part, uriformatter=None):
        try:
            uri = self.uriformatter[part.tag](self.find_attributes([part]))
        except KeyError:
            if uriformatter:
                uri = uriformatter(self.find_attributes([part]))
            else:
                uri = self.sfs_format_uri(self.find_attributes([part]))
        except AttributeError:
            # Normal error from eglag_format_uri
            return part.text
#        except Exception as e:
#            # FIXME: We should maybe not swallow all other errors...
#            # If something else went wrong, just return the plaintext
#            log.warning("(unknown): Unable to format link for text %s (production %s): %s: %s" %
#                        (part.text, part.tag, type(e).__name__, e))
#            return part.text
#
        if self.verbose:
            print((
                (". " * self.depth) + "format_generic_link: uri is %s" % uri))
        if not uri:
            # the formatting function decided not to return a URI for
            # some reason (maybe it was a partial/relative reference
            # without a proper base uri context
            return part.text
        elif self.predicate:
            return LinkSubject(part.text, uri=uri, predicate=self.predicate)
        else:
            return Link(part.text, uri=uri)

    # FIXME: unify this with format_generic_link
    def format_custom_link(self, attributes, text, production):
        try:
            uri = self.uriformatter[production](attributes)
        except KeyError:
            uri = self.sfs_format_uri(attributes)

        if not uri:
            # the formatting function decided not to return a URI for
            # some reason (maybe it was a partial/relative reference
            # without a proper base uri context
            return text
        elif self.predicate:
            return LinkSubject(text, uri=uri, predicate=self.predicate)
        else:
            return Link(text, uri=uri)

    #
    # KOD FÖR LAGRUM
    def clear_state(self):
        self.currentlaw = None
        self.currentchapter = None
        self.currentsection = None
        self.currentpiece = None

    def normalize_sfsid(self, sfsid):
        # sometimes '1736:0123 2' is given as '1736:0123 s. 2' or
        # '1736:0123.2'. This fixes that.
        sfsid = re.sub(r'(\d+:\d+)\.(\d)', r'\1 \2', sfsid)
        sfsid = sfsid.replace("\n", " ")
        # return sfsid.replace('s. ','').replace('s.','') # more advanced
        # normalizations to come...
        return sfsid

    def normalize_lawname(self, lawname):
        lawname = lawname.replace('|', '').replace('_', ' ').lower()
        if lawname.endswith('s'):
            lawname = lawname[:-1]
        return lawname

    def namedlaw_to_sfsid(self, text, normalize=True):
        if normalize:
            text = self.normalize_lawname(text)

        nolaw = [
            'aktieslagen',
            'anordningen',
            'anordningen',
            'anslagen',
            'arbetsordningen',
            'associationsformen',
            'avfallsslagen',
            'avslagen',
            'avvittringsutslagen',
            'bergslagen',
            'beskattningsunderlagen',
            'bolagen',
            'bolagsordningen',
            'bolagsordningen',
            'dagordningen',
            'djurslagen',
            'dotterbolagen',
            'emballagen',
            'energislagen',
            'ersättningsformen',
            'ersättningsslagen',
            'examensordningen',
            'finansbolagen',
            'finansieringsformen',
            'fissionsvederlagen',
            'flygbolagen',
            'fondbolagen',
            'förbundsordningen',
            'föreslagen',
            'företrädesordningen',
            'förhandlingsordningen',
            'förlagen',
            'förmånsrättsordningen',
            'förmögenhetsordningen',
            'förordningen',
            'förslagen',
            'försäkringsaktiebolagen',
            'försäkringsbolagen',
            'gravanordningen',
            'grundlagen',
            'handelsplattformen',
            'handläggningsordningen',
            'inkomstslagen',
            'inköpssamordningen',
            'kapitalunderlagen',
            'klockslagen',
            'kopplingsanordningen',
            'låneformen',
            'mervärdesskatteordningen',
            'nummerordningen',
            'omslagen',
            'ordalagen',
            'pensionsordningen',
            'renhållningsordningen',
            'representationsreformen',
            'rättegångordningen',
            'rättegångsordningen',
            'rättsordningen',
            'samordningen',
            'samordningen',
            'skatteordningen',
            'skatteslagen',
            'skatteunderlagen',
            'skolformen',
            'skyddsanordningen',
            'slagen',
            'solvärmeanordningen',
            'storslagen',
            'studieformen',
            'stödformen',
            'stödordningen',
            'stödordningen',
            'säkerhetsanordningen',
            'talarordningen',
            'tillslagen',
            'tivolianordningen',
            'trafikslagen',
            'transportanordningen',
            'transportslagen',
            'trädslagen',
            'turordningen',
            'underlagen',
            'uniformen',
            'uppställningsformen',
            'utvecklingsbolagen',
            'varuslagen',
            'verksamhetsformen',
            'vevanordningen',
            'vårdformen',
            'ägoanordningen',
            'ägoslagen',
            'ärendeslagen',
            'åtgärdsförslagen',
        ]
        if text in nolaw:
            return None

        if text in self.currentlynamedlaws:
            return self.currentlynamedlaws[text]
        elif text in self.namedlaws:
            return self.namedlaws[text]
        else:
            if self.verbose:
                # print "(unknown): I don't know the ID of named law [%s]" % text
                log.warning(
                    "(unknown): I don't know the ID of named law [%s]" % text)
            return None

    attributemap = {"year": RPUBL.arsutgava,
                    "no": RPUBL.lopnummer,
                    "chapter": RPUBL.kapitelnummer,
                    "section": RPUBL.paragrafnummer
                    }

    def graph_from_attributes(self, attributes):
        g = Graph()
        b = BNode()
        for k, v in attributes.items():
            if k in self.attributemap:
                g.add((b, self.attributemap[k], Literal(v)))
            else:
                self.log.error("Can't map attribute %s to RDF predicate" % k)
        return g, b

    
    def sfs_format_uri(self, attributes):
        if 'law' not in attributes and not self.allow_relative:
            return None
        piecemappings = {'första': '1',
                         'andra': '2',
                         'tredje': '3',
                         'fjärde': '4',
                         'femte': '5',
                         'sjätte': '6',
                         'sjunde': '7',
                         'åttonde': '8',
                         'nionde': '9'}
        # possibly do something smart with piecemappings

        attributeorder = ['law', 'chapter', 'section',
                          'element', 'piece', 'item', 'itemnumeric', 'sentence']

        # possibly complete attributes with data from
        # baseuri_attributes as needed
        if self.allow_relative:
            specificity = False
            for a in attributeorder:
                if a in attributes:
                    specificity = True  # don't complete further than this
                elif not specificity:
                    attributes[a] = self.baseuri_attributes[a]
        # munge graph a little further to be able to map to RDF
        if "law" in attributes:
            attributes["year"], attributes["no"] = attributes["law"].split(":")
            del attributes["law"]
        g, b = self.graph_from_attributes(attributes)
        # need also to add a rpubl:forfattningssamling triple -- i
        # think this is the place to do it. Problem is how we get
        # access to the URI for SFS -- it can be
        # <https://lagen.nu/dataset/sfs> or
        # <http://rinfo.lagrummet.se/serie/fs/sfs>. The information is
        # available in the config graph, which isn't easily
        # retrievable from self.minter. So we do it the hard way.
        rg = self.minter.space.templates[0].resource.graph
        # get the abbrSlug subproperty. FIXME: do this properly
        abbrSlug = rg.value(predicate=RDF.type, object=RDF.Property)
        fsuri = rg.value(predicate=abbrSlug, object=Literal("sfs"))
        assert fsuri, "Couldn't find URI for forfattningssamling 'sfs'"
        g.add((b, RPUBL.forfattningssamling, fsuri))
        return self.minter.space.coin_uri(g.resource(b))

    def format_ChapterSectionRefs(self, root):
        assert(root.tag == 'ChapterSectionRefs')
        assert(len(root.nodes) == 3)  # ChapterRef, wc, SectionRefs

        part = root.nodes[0]
        self.currentchapter = part.nodes[0].text.strip()

        if self.currentlaw:
            res = [self.format_custom_link({'law': self.currentlaw,
                                            'chapter': self.currentchapter},
                                           part.text,
                                           part.tag)]
        else:
            res = [self.format_custom_link({'chapter': self.currentchapter},
                                           part.text,
                                           part.tag)]

        res.extend(self.formatter_dispatch(root.nodes[1]))
        res.extend(self.formatter_dispatch(root.nodes[2]))
        self.currentchapter = None
        return res

    def format_ChapterSectionPieceRefs(self, root):
        assert(root.nodes[0].nodes[0].tag == 'ChapterRefID')
        self.currentchapter = root.nodes[0].nodes[0].text.strip()
        res = []
        for node in root.nodes:
            res.extend(self.formatter_dispatch(node))
        return res

    def format_LastSectionRef(self, root):
        # the last section ref is a bit different, since we want the
        # ending double section mark to be part of the link text
        assert(root.tag == 'LastSectionRef')
        assert(len(root.nodes) == 3)  # LastSectionRefID, wc, DoubleSectionMark
        sectionrefid = root.nodes[0]
        sectionid = sectionrefid.text

        return [self.format_generic_link(root)]

    def format_SectionPieceRefs(self, root):
        assert(root.tag == 'SectionPieceRefs')
        self.currentsection = root.nodes[0].nodes[0].text.strip()

        res = [self.format_custom_link(self.find_attributes([root.nodes[2]]),
                                       "%s %s" % (root.nodes[0]
                                                  .text, root.nodes[2].text),
                                       root.tag)]
        for node in root.nodes[3:]:
            res.extend(self.formatter_dispatch(node))

        self.currentsection = None
        return res

    def format_SectionPieceItemRefs(self, root):
        assert(root.tag == 'SectionPieceItemRefs')
        self.currentsection = root.nodes[0].nodes[0].text.strip()
        self.currentpiece = root.nodes[2].nodes[0].text.strip()

        res = [self.format_custom_link(self.find_attributes([root.nodes[2]]),
                                       "%s %s" % (root.nodes[0]
                                                  .text, root.nodes[2].text),
                                       root.tag)]

        for node in root.nodes[3:]:
            res.extend(self.formatter_dispatch(node))

        self.currentsection = None
        self.currentpiece = None
        return res

    # This is a special case for things like '17-29 och 32 §§ i lagen
    # (2004:575)', which picks out the LawRefID first and stores it in
    # .currentlaw, so that find_attributes finds it
    # automagically. Although now it seems to be branching out and be
    # all things to all people.
    def format_ExternalRefs(self, root):
        assert(root.tag == 'ExternalRefs')
        # print "DEBUG: start of format_ExternalRefs; self.currentlaw is %s" %
        # self.currentlaw

        lawrefid_node = self.find_node(root, 'LawRefID')
        if lawrefid_node is None:
            # Ok, no explicit LawRefID found, lets see if this is a named law that we have the ID for
            # namedlaw_node = self.find_node(root, 'NamedLawExternalLawRef')
            namedlaw_node = self.find_node(root, 'NamedLaw')
            if namedlaw_node is None:
                # As a last chance, this might be a reference back to a previously
                # mentioned law ("...enligt 4 § samma lag")
                samelaw_node = self.find_node(root, 'SameLaw')
                assert(samelaw_node is not None)
                if self.lastlaw is None:
                    log.warning(
                        "(unknown): found reference to \"{samma,nämnda} {lag,förordning}\", but self.lastlaw is not set")

                self.currentlaw = self.lastlaw
            else:
                # the NamedLaw case
                self.currentlaw = self.namedlaw_to_sfsid(namedlaw_node.text)
                if self.currentlaw is None:
                    # unknow law name - in this case it's better to
                    # bail out rather than resolving chapter/paragraph
                    # references relative to baseuri (which is almost
                    # certainly wrong)
                    return [root.text]
        else:
            self.currentlaw = lawrefid_node.text
            if self.find_node(root, 'NamedLaw'):
                namedlaw = self.normalize_lawname(
                    self.find_node(root, 'NamedLaw').text)
                # print "remember that %s is %s!" % (namedlaw, self.currentlaw)
                self.currentlynamedlaws[namedlaw] = self.currentlaw

        # print "DEBUG: middle of format_ExternalRefs; self.currentlaw is %s" %
        # self.currentlaw
        if self.lastlaw is None:
            # print "DEBUG: format_ExternalRefs: setting self.lastlaw to %s" %
            # self.currentlaw
            self.lastlaw = self.currentlaw

        # if the node tree only contains a single reference, it looks
        # better if the entire expression, not just the
        # chapter/section part, is linked. But not if it's a
        # "anonymous" law ('1 § i lagen (1234:234) om blahonga')
        if (len(self.find_nodes(root, 'GenericRefs')) == 1 and
            len(self.find_nodes(root, 'SectionRefID')) == 1 and
                len(self.find_nodes(root, 'AnonymousExternalLaw')) == 0):
            res = [self.format_generic_link(root)]
        else:
            res = self.format_tokentree(root)

        return res

    def format_SectionItemRefs(self, root):
        assert(root.nodes[0].nodes[0].tag == 'SectionRefID')
        self.currentsection = root.nodes[0].nodes[0].text.strip()
        # res = self.formatter_dispatch(root.nodes[0]) # was formatter_dispatch(self.root)
        res = self.format_tokentree(root)
        self.currentsection = None
        return res

    def format_PieceItemRefs(self, root):
        self.currentpiece = root.nodes[0].nodes[0].text.strip()
        res = [self.format_custom_link(
            self.find_attributes([root.nodes[2].nodes[0]]),
               "%s %s" % (root.nodes[0].text, root.nodes[2].nodes[0].text),
               root.tag)]
        for node in root.nodes[2].nodes[1:]:
            res.extend(self.formatter_dispatch(node))

        self.currentpiece = None
        return res

    def format_ChapterSectionRef(self, root):
        assert(root.nodes[0].nodes[0].tag == 'ChapterRefID')
        self.currentchapter = root.nodes[0].nodes[0].text.strip()
        return [self.format_generic_link(root)]

    def format_AlternateChapterSectionRefs(self, root):
        assert(root.nodes[0].nodes[0].tag == 'ChapterRefID')
        self.currentchapter = root.nodes[0].nodes[0].text.strip()
        # print "Self.currentchapter is now %s" % self.currentchapter
        res = self.format_tokentree(root)
        self.currentchapter = None
        return res

    def format_ExternalLaw(self, root):
        self.currentchapter = None
        return self.formatter_dispatch(root.nodes[0])

    def format_ChangeRef(self, root):
        id = self.find_node(root, 'LawRefID').data
        return [self.format_custom_link({'lawref': id},
                                        root.text,
                                        root.tag)]

    def format_SFSNr(self, root):
        if self.baseuri is None:
            sfsid = self.find_node(root, 'LawRefID').data
            g = self.graph_from_attributes({'law': sfsid})
            baseuri = self.minter.space.compute_uri(g)
            self.baseuri_attributes = {'baseuri': baseuri}

        return self.format_tokentree(root)

    def format_NamedExternalLawRef(self, root):
        resetcurrentlaw = False
        # print "format_NamedExternalLawRef: self.currentlaw is %r"  % self.currentlaw
        if self.currentlaw is None:
            resetcurrentlaw = True
            lawrefid_node = self.find_node(root, 'LawRefID')
            if lawrefid_node is None:
                self.currentlaw = self.namedlaw_to_sfsid(root.text)
            else:
                self.currentlaw = lawrefid_node.text
                namedlaw = self.normalize_lawname(
                    self.find_node(root, 'NamedLaw').text)
                # print "remember that %s is %s!" % (namedlaw, self.currentlaw)
                self.currentlynamedlaws[namedlaw] = self.currentlaw
            # print "format_NamedExternalLawRef: self.currentlaw is now %r"  %
            # self.currentlaw

        # print "format_NamedExternalLawRef: self.baseuri is %r" % self.baseuri
        # if we can't find a ID for this law, better not <link> it
        if self.currentlaw is None:
            res = [root.text]
        else:
            res = [self.format_generic_link(root)]

        # print "format_NamedExternalLawRef: self.baseuri is %r" % self.baseuri
        if self.baseuri is None and self.currentlaw is not None:
            # print "format_NamedExternalLawRef: setting baseuri_attributes"
            # use this as the new baseuri_attributes
            m = self.re_urisegments.match(self.currentlaw)
            if m:
                self.baseuri_attributes = {'baseuri': m.group(1),
                                           'law': m.group(2),
                                           'chapter': m.group(6),
                                           'section': m.group(8),
                                           'piece': m.group(10),
                                           'item': m.group(12)}
            else:
                g = self.graph_from_attributes({'law': self.currentlaw})
                self.baseuri_attributes = {
                    'baseuri': self.minter.space.compute_uri(g)
                    }

        if resetcurrentlaw:
            if self.currentlaw is not None:
                self.lastlaw = self.currentlaw
            self.currentlaw = None
        return res

    #
    # KOD FÖR KORTLAGRUM
    def format_AbbrevLawNormalRef(self, root):
        lawabbr_node = self.find_node(root, 'LawAbbreviation')
        self.currentlaw = self.namedlaw_to_sfsid(
            lawabbr_node.text, normalize=False)
        res = [self.format_generic_link(root)]
        if self.currentlaw is not None:
            self.lastlaw = self.currentlaw
        self.currentlaw = None
        return res

    def format_AbbrevLawShortRef(self, root):
        assert(root.nodes[0].tag == 'LawAbbreviation')
        assert(root.nodes[2].tag == 'ShortChapterSectionRef')
        self.currentlaw = self.namedlaw_to_sfsid(
            root.nodes[0].text, normalize=False)
        shortsection_node = root.nodes[2]
        assert(shortsection_node.nodes[0].tag == 'ShortChapterRefID')
        assert(shortsection_node.nodes[2].tag == 'ShortSectionRefID')
        self.currentchapter = shortsection_node.nodes[0].text
        self.currentsection = shortsection_node.nodes[2].text

        res = [self.format_generic_link(root)]

        self.currentchapter = None
        self.currentsection = None
        self.currentlaw = None
        return res

    #
    # KOD FÖR FORARBETEN
    def forarbete_format_uri(self, attributes):
        g = self.graph_from_attributes(attributes)
        return self.minter.space.compute_uri(g)

    def format_ChapterSectionRef(self, root):
        assert(root.nodes[0].nodes[0].tag == 'ChapterRefID')
        self.currentchapter = root.nodes[0].nodes[0].text.strip()
        return [self.format_generic_link(root)]

    #
    # KOD FÖR EULAGSTIFTNING
    def eglag_format_uri(self, attributes):
        if not 'akttyp' in attributes:
            if 'forordning' in attributes:
                attributes['akttyp'] = 'förordning'
            elif 'direktiv' in attributes:
                attributes['akttyp'] = 'direktiv'
        if 'akttyp' not in attributes:
            raise AttributeError("Akttyp saknas")
        g = self.graph_from_attributes(attributes)
        return self.minter.space.compute_uri(g)


    # KOD FÖR RATTSFALL
    def rattsfall_format_uri(self, attributes):

        # res = self.baseuri_attributes['baseuri']
        if 'nja' in attributes:
            attributes['domstol'] = attributes['nja']

        assert 'domstol' in attributes, "No court provided"
        assert attributes[
            'domstol'] in containerid, "%s is an unknown court" % attributes['domstol']
        
        g = self.graph_from_attributes(attributes)
        return self.minter.space.compute_uri(g)

    #
    # KOD FÖR EGRÄTTSFALL
    def egrattsfall_format_uri(self, attributes):
        descriptormap = {'C': 'J',  # Judgment of the Court
                         'T': 'A',  # Judgment of the Court of First Instance
                         'F': 'W',  # Judgement of the Civil Service Tribunal
                         }
        # FIXME: Change this before the year 2054 (as ECJ will
        # hopefully have fixed their case numbering by then)
        if len(attributes['year']) == 2:
            if int(attributes['year']) < 54:
                year = "20" + attributes['year']
            else:
                year = "19" + attributes['year']
        else:
            year = attributes['year']

        serial = '%04d' % int(attributes['serial'])
        descriptor = descriptormap[attributes['decision']]
        g = self.graph_from_attributes(year, descriptor, serial)
        return self.minter.compute_uri(g)
