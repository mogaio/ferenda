# -*- coding: utf-8 -*-
"""A bunch of helper functions for analyzing pdf files."""
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

# stdlib
import logging
import json
from collections import Counter
from io import BytesIO
from itertools import chain
from math import floor, ceil

# 3rd party
from cached_property import cached_property

# mine
from .pdfreader import Page
from ferenda import util


class PDFAnalyzer(object):

    """Create a analyzer for the given pdf file.

    The primary purpose of an analyzer is to determine margins and
    other spatial metrics of a document, and identifiy common
    typographic styles for default text, title and headings. This
    is done by calling the :py:meth:`~ferenda.PDFAnalyzer.metrics`
    method.

    The analysis is done in several steps. The properties of all
    textboxes on each page is collected in several
    :py:class:`collections.Counter` objects. These counters are then
    statistically analyzed in a series of functions to yield these
    metrics.

    If different analyzis logic, or additional metrics, are desired,
    this class should be inherited and some methods/properties
    overridden.

    :param pdf: The pdf file to analyze.
    :type  pdf: ferenda.PDFReader

    """

    twopage = True
    """Whether or not the document is expected to have different margins
    depending on whether it's a even or odd page.

    """

    style_significance_threshold = 0.005
    """"The amount of use (as compared to the rest of the document that a
    style must have to be considered significant.

    """

    header_significance_threshold = 0.002
    """The maximum amount (expressed as part of the entire text amount) of
    text that can occur on the top of the page for it to be considered
    part of the header.

    """

    # this is suitable for overriding, eg if you know that no pagenumbers
    # occur in the footer
    footer_significance_threshold = 0.002
    """The maximum amount (expressed as part of the entire text amount) of
    text that can occur on the bottom of the page for it to be
    considered part of the footer.

    """

    def __init__(self, pdf):
        # FIXME: in time, we'd like to make it possible to specify
        # multiple pdf files (either because a single logical document
        # is split into several files, or because the user wants to
        # analyze a bunch of docs in one go).
        self.pdf = pdf
        self.scanned_source = False

    @cached_property
    def documents(self):
        """Attempts to distinguish different logical document (eg parts with
        differing pagesizes/margins/styles etc) within this PDF.

        You should override this method if you want to provide your
        own document segmentation logic.

        :returns: Tuples (startpage, pagecount, tag) for the different identified
                  documents
        :rtype: list

        """
        return [(0, len(self.pdf), 'main')]

    def metrics(self, metricspath=None, plotpath=None,
                startpage=0, pagecount=None, force=False):
        """Calculate and return the metrics for this analyzer.

        metrics is a set of named properties in the form of a
        dict. The keys of the dict can represent margins or other
        measurements of the document (left/right margins,
        header/footer etc) or font styles used in the document (eg.
        default, title, h1 -- h3). Style values are in turn dicts
        themselves, with the keys 'family' and 'size'.

        :param metricspath: The path of a JSON file used as cache for the
                             calculated metrics
        :type  metricspath: str
        :param plotpath: The path to write a PNG file with histograms for
                         different values (for debugging).
        :type plotpath: str
        :param startpage: starting page for the analysis
        :type startpage: int
        :param startpage: number of pages to analyze (default: all available)
        :type startpage: int
        :param force: Perform analysis even if cached JSON metrics exists.
        :type force: bool
        :returns: calculated metrics
        :rtype: dict

        The default implementation will try to find out values for the
        following metrics:

        ================== ===================================================
        key                description
        ================== ===================================================
        leftmargin         position of left margin (for odd pages if
                           twopage = True)
        rightmargin        position of right margin (for odd pages if
                           twopage = True)
        leftmargin_even    position of left margin for even pages

        rightmargin_even   position of right margin for right pages

        topmargin          position of header zone

        bottommargin       position of footer zone

        default            style used for default text

        title              style used for main document title (on front page)

        h1                 style used for level 1 headings

        h2                 style used for level 2 headings

        h3                 style used for level 3 headings
        ================== ===================================================

        Subclasses might add (or remove) from the above.

        """
        if (not force and
                metricspath and
                util.outfile_is_newer([self.pdf.filename], metricspath)):
            with open(metricspath) as fp:
                return json.load(fp)

        if pagecount is None:
            pagecount = len(self.pdf) - startpage

        hcounters = self.count_horizontal_margins(startpage, pagecount)
        vcounters = self.count_vertical_margins(startpage, pagecount)
        stylecounters = self.count_styles(startpage, pagecount)

        hmetrics = self.analyze_horizontal_margins(hcounters)
        vmetrics = self.analyze_vertical_margins(vcounters)
        stylemetrics = self.analyze_styles(stylecounters)

        margincounters = dict(chain(hcounters.items(), vcounters.items()))
        allmetrics = dict(chain(hmetrics.items(), vmetrics.items(), stylemetrics.items()))
        allmetrics['scanned_source'] = self.scanned_source

        if plotpath:
            self.plot(plotpath, margincounters, stylecounters, allmetrics)
        if metricspath:
            util.ensure_dir(metricspath)
            with open(metricspath, "w") as fp:
                s = json.dumps(allmetrics, indent=4, separators=(', ', ': '), sort_keys=True)
                fp.write(s)
        return allmetrics

    def textboxes(self, startpage, pagecount):
        """Generate a stream of (pagenumber, textbox) tuples consisting of all
        pages/textboxes from startpage to pagecount.

        """
        for page in self.pdf[startpage:startpage + pagecount]:
            for textbox in page:
                yield page.number, textbox

    def count_horizontal_margins(self, startpage, pagecount):
        """Return a dict of Counter objects for all the horizontally oriented
        textbox properties (number of textboxes starting/ending at different
        positions).

        The set of counters is determined by setup_horizontal_counters.
        """

        counters = self.setup_horizontal_counters()
        for pagenumber, textbox in self.textboxes(startpage, pagecount):
            self.count_horizontal_textbox(pagenumber, textbox, counters)
        for page in self.pdf[startpage:startpage + pagecount]:
            counters['pagewidth'][page.width] += 1
        return counters

    def setup_horizontal_counters(self):
        """Create initial set of horizontal counters."""
        counters = {'leftmargin': Counter(),
                    'rightmargin': Counter(),
                    'pagewidth': Counter()}
        if self.twopage:
            counters['leftmargin_even'] = Counter()
            counters['rightmargin_even'] = Counter()
        return counters

    def count_horizontal_textbox(self, pagenumber, textbox, counters):
        """Add a single textbox to the set of horizontal counters."""
        if self.twopage and pagenumber % 2 == 0:
            counters['leftmargin_even'][textbox.left] += 1
            counters['rightmargin_even'][textbox.right] += 1
        else:
            counters['leftmargin'][textbox.left] += 1
            counters['rightmargin'][textbox.right] += 1

    def count_vertical_margins(self, startpage, pagecount):
        counters = self.setup_vertical_counters()
        for pagenumber, textbox in self.textboxes(startpage, pagecount):
            self.count_vertical_textbox(pagenumber, textbox, counters)
        for page in self.pdf[startpage:startpage + pagecount]:
            counters['pageheight'][page.height] += 1
        return counters

    def setup_vertical_counters(self):
        counters = {'topmargin': Counter(),
                    'bottommargin': Counter(),
                    'pageheight': Counter()}
        return counters

    def count_vertical_textbox(self, pagenumber, textbox, counters):
        text = str(textbox).strip()
        counters['topmargin'][textbox.top] += len(text)
        counters['bottommargin'][textbox.bottom] += len(text)

    def count_styles(self, startpage, pagecount):
        c = Counter()
        for pagenumber, textbox in self.textboxes(startpage, pagecount):
            self.count_styles_textbox(pagenumber, textbox, c)
        return c

    def count_styles_textbox(self, pagenumber, textbox, counter):
        text = str(textbox).strip()
        fonttuple = (textbox.font.family, textbox.font.size)
        counter[fonttuple] += len(text)

    def analyze_vertical_margins(self, vcounters):
        # now find probable header and footer zones. default algorithm:
        # max 0.2 % of text content can be in the header/footer zone. (on
        # a page of 2000 chars, only 4 can be in the footer)
        maxcount = self.header_significance_threshold * sum(vcounters['topmargin'].values())
        charcount = 0
        for i in range(max(vcounters['pageheight'])):
            charcount += vcounters['topmargin'].get(i, 0)
            if charcount > maxcount:
                header = i - 1
                break
        else:
             header = maxcount
        charcount = 0
        maxcount = self.footer_significance_threshold * sum(vcounters['topmargin'].values())
        for i in range(max(vcounters['pageheight']) - 1, -1, -1):
            charcount += vcounters['bottommargin'].get(i, 0)
            if charcount > maxcount:
                footer = i + 1
                break
        else:
             footer = maxcount   
        return {'topmargin': header,
                'bottommargin': footer,
                'pageheight': max(vcounters['pageheight'])}

    # subclasses can (should) add metrics like parindent and secondcolumn
    def analyze_horizontal_margins(self, vcounters):
        vmargins = {}
        pagewidth = vcounters['pagewidth'].most_common(1)[0][0]
        midpage = pagewidth / 2
        # find the probable left margin = the place where most textboxes start
        l = self.filterdict(vcounters['leftmargin'], lambda x: x < midpage)
        r = self.filterdict(vcounters['rightmargin'], lambda x: x > midpage)
        if l:
            vmargins['leftmargin'] = self.findmargin(l, trunc_func=floor, quantize=self.scanned_source)
        if r:
            vmargins['rightmargin'] = self.findmargin(r, trunc_func=ceil, quantize=True)
        if self.twopage:
            le = self.filterdict(vcounters['leftmargin_even'], lambda x: x < midpage)
            re = self.filterdict(vcounters['rightmargin_even'], lambda x: x > midpage)
            if le:
                vmargins['leftmargin_even'] = self.findmargin(le, trunc_func=floor, quantize=self.scanned_source)
            if re:
                vmargins['rightmargin_even'] = self.findmargin(re, trunc_func=ceil, quantize=True)
        vmargins['pagewidth'] = max(vcounters['pagewidth'])
        return vmargins

    def filterdict(self, counter, filter_func=None):
        if filter_func is None:
            filter_func = lambda x: True
        newcounter = Counter()
        for x in counter:
            if filter_func(x):
                newcounter[x] = counter[x]
        return newcounter

    def findmargin(self, counter, trunc_func=round, quantize=False):
        if not quantize:
            return counter.most_common(1)[0][0]
        else:
            # Taking most_common() works badly for scanned sources
            # which might have 14 left edges (le) starting at 101, 13
            # at 103, 9 at 99 and so on, when the "real" leftmargin is
            # at 100. A naive way is to "quantize" everything by eg
            # dividing everything by 4 or 10 or something (ie lowering
            # resolution), finding the most_common of that.
            #
            # also, it works bad for right edges in general
            binsize = 10 # FIXME: make configurable or selfadjusting
            lowres = Counter()
            for val in counter:
                lowresbin = trunc_func(val / binsize)
                lowres[lowresbin * binsize] += counter[val]

            # it's entirely possible that two or more bins will have the same count. Find out how many, and select the best candidate
            prevcount = None
            candidates = []
            for val, count in lowres.most_common():
                if prevcount and count != prevcount:
                    # ok we're done, select the best candidate
                    if trunc_func == ceil:
                        select_func = max
                    elif trunc_func == floor:
                        select_func = min
                    else:
                        # the average value of all candidates
                        select_func = lambda l: sum(l)/len(l)
                    return select_func(candidates)
                else:
                    candidates.append(val)
                    prevcount = count
            return candidates[0]  # this should only happen if we only have a single candidate


        
    def fontsize_key(self, fonttuple):
        family, size = fonttuple
        if "Bold" in family:
            weight = 2
        elif "Italic" in family:
            weight = 1
        else:
            weight = 0
        return (size, weight)

    def fontdict(self, fonttuple):
        return {'family': fonttuple[0],
                'size': fonttuple[1]}

    def analyze_styles(self, styles):
        styledefs = {}

        # default style: the one that's most common
        ds = styles.most_common(1)[0][0]
        styledefs['default'] = self.fontdict(ds)

        # h1 - h3: Take all styles larger than or equal to default,
        # with significant use (each > 0.5% of all chars from page 2
        # onwards, as the front page often uses nontypical styles),
        # then order styles by font size.
        significantuse = sum(styles.values()) * self.style_significance_threshold
        sortedstyles = sorted(styles, key=self.fontsize_key, reverse=True)
        largestyles = [x for x in sortedstyles if
                       (self.fontsize_key(x) > self.fontsize_key(ds) and
                        styles[x] > significantuse)]

        for style in ('h1', 'h2', 'h3'):
            if largestyles:  # any left?
                styledefs[style] = self.fontdict(largestyles.pop(0))
        return styledefs

    def drawboxes(self, outfilename, gluefunc=None, startpage=0,
                  pagecount=None, counters=None, metrics=None):
        """Create a copy of the parsed PDF file, but with the textboxes
        created by ``gluefunc`` clearly marked, and metrics shown on
        the page.

        .. note::

           This requires PyPDF2 and reportlab, which aren't installed
           by default. Reportlab (3.*) only works on py27+ and py33+

        """
        try:
            import PyPDF2
            from reportlab.pdfgen.canvas import Canvas
        except ImportError:
            raise ImportError("You need PyPDF2 and reportlab installed")
        styles = {}
        for k, v in metrics.items():
            if isinstance(v, dict):
                styles[(v['family'], v['size'])] = k
        log = logging.getLogger("pdfanalyze")
        packet = None
        output = PyPDF2.PdfFileWriter()
        fp = open(self.pdf.filename, "rb")
        existing_pdf = PyPDF2.PdfFileReader(fp)
        pageidx = 0
        tbidx = 0
        sf = 2 / 3.0  # scaling factor -- mapping between units produced by
        # pdftohtml and units used by reportlab
        dirty = False

        for tb in self.pdf.textboxes(gluefunc, pageobjects=True):
            if isinstance(tb, Page):
                if dirty:
                    canvas.save()
                    packet.seek(0)
                    new_pdf = PyPDF2.PdfFileReader(packet)
                    # print("Merging a new page into %s" % id(existing_page))

                    # this SHOULD place the new page (that only
                    # contains boxes and lines) on top of the existing
                    # page. Only problem is that the image (from the
                    # existing page) obscures those lines (contrary to
                    # documentation)
                    try:
                        new_page = new_pdf.getPage(0)
                        existing_page.mergePage(new_page)
                    except Exception as e:
                        log.error("Couldn't merge page %s: %s: %s" % (pageidx, type(e), e))
                    output.addPage(existing_page)

                    # alternate way: merge the existing page on top of
                    # the new. This doesn't seem to work any better,
                    # and creates issues with scaling.
                    #
                    # new_page = new_pdf.getPage(0)
                    # new_page.mergePage(existing_page)
                    # output.addPage(new_page)

                # print("Loading page %s" % pageidx)
                existing_page = existing_pdf.getPage(pageidx)
                pageidx += 1
                mb = existing_page.mediaBox
                horizontal_scale = float(mb.getHeight()) / tb.height
                vertical_scale = float(mb.getWidth()) / tb.width
                log.debug(
                    "Loaded page %s - Scaling %s, %s" %
                    (pageidx, horizontal_scale, vertical_scale))
                packet = BytesIO()
                canvas = Canvas(packet, pagesize=(tb.height, tb.width),
                                bottomup=False)
                # not sure how the vertical value 50 is derived...
                canvas.translate(0, 50)
                canvas.scale(horizontal_scale, vertical_scale)
                canvas.setStrokeColorRGB(0.2, 0.5, 0.3)

                # now draw margins on the page
                for k, v in metrics.items():
                    if isinstance(v, int):
                        if k in ('topmargin', 'bottommargin', 'pageheight'):
                            # horiz line
                            canvas.line(0, v, tb.width, v)
                            canvas.drawString(0, v, k)
                        else:
                            if ((k.endswith("_even") and (pageidx + 1) % 2 == 1) or
                                    (not k.endswith("_even") and (pageidx + 1) % 2 == 0) or
                                    (not self.twopage)):
                                # vert line
                                canvas.line(v, 0, v, tb.height)
                                canvas.drawString(v, tb.height - 2, k)
                # for k, v in counters:
                # for each area in header, footer, leftmarg[_even], rightmarg[_even]:
                #    select proper counter to draw in each area:
                #      (headercounter->left gutter,
                #       footercounter->right gutter,
                #       leftmargcounter->header,
                #       rightmargcounter->footer)
                #   find the most frequent value in the selected counter, normalize agaist the space in the area
                #   for each value of the counter draw single-width line at correct posiion
                tbidx = 0
            else:
                tbidx += 1
                dirty = True
                # for each textbox draw a square
                # add sequence number for textbox in lower right corner
                # if textbox style matches any in metrics, add the style name in upper lft
                # corner
                canvas.rect(tb.left, tb.top,
                            tb.width, tb.height)
                canvas.drawString(tb.left, tb.top, str(tbidx))
                fonttuple = (tb.font.family, tb.font.size)
                if tb.lines > 1:  # need at least 2 lines to calc
                    # linespacing to calculate lineheight, first
                    # estimate size of box except last line, but
                    # including the spacing from the previous
                    # line. Lets hope font.size uses the same scale as
                    # tb.height! (both should use points, right?)
                    linespacing = ((tb.height - (tb.font.size/horizontal_scale)) / (tb.lines - 1)) / tb.font.size
                else:
                    linespacing = ""
                if fonttuple in styles:
                    lbl = "%s (%s) %s" % (styles[fonttuple], tb.lines, linespacing)
                else:
                    lbl = "(%s) %s" % (tb.lines, linespacing)
                canvas.drawString(tb.right, tb.bottom, lbl)
        packet.seek(0)
        canvas.save()
        new_pdf = PyPDF2.PdfFileReader(packet)
        # print("Merging final new page into %s" % id(existing_page))
        existing_page.mergePage(new_pdf.getPage(0))
        output.addPage(existing_page)
        outputStream = open(outfilename, "wb")
        output.write(outputStream)
        outputStream.close()
        log.debug("wrote %s" % outfilename)
        fp.close()

    def plot(self, filename, margincounters, stylecounters, metrics):
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except ImportError:
            raise ImportError("You need matplotlib installed")
        # plt.style.use('ggplot')  # looks good but makes histograms unreadable
        matplotlib.rcParams.update({'font.size': 8})
        # width, height in inches
        plt.figure(figsize=((len(margincounters)) * 2, 7)) 

        # if 6 counters:
        # +0,0--+ +0,1--+ +0,2--+ +0,3--+
        # | LM  | | LEM | | RM  | | REM |
        # +-----+ +-----+ +-----+ +-----+
        # +1,0--+ +1,1--+ +1,2 colspan=2+
        # | TM  | | BM  | |    Styles   |
        # +-----+ +-----+ +-------------+
        #
        # if 4 counters:
        # +0,0--+ +0,1--+ +0,2--+
        # | LM  | | RM  | | TM  |
        # +-----+ +-----+ +-----+
        # +1,0--+ +1,1 colspan=2+
        # | BM  | |    Styles   |
        # +-----+ +-------------+

        # disregard the pageheight/pagewidth counters
        pagewidth = max(margincounters['pagewidth'])
        del margincounters['pagewidth']
        pageheight = max(margincounters['pageheight'])
        del margincounters['pageheight']
        if len(margincounters) == 4:
            coords = ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1))
            grid = (2, 3)
        elif len(margincounters) == 6:
            coords = ((0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2))
            grid = (2, 4)
        else:
            # FIXME: make this dynamic
            raise ValueError("Can't layout other # of counters than 4 or 6")
        marginplots = [plt.subplot2grid(grid, pos) for pos in coords[:-1]]
        self.plot_margins(marginplots, margincounters, metrics,
                          pagewidth, pageheight)

        styleplot = plt.subplot2grid(grid, coords[-1], colspan=2)
        self.plot_styles(styleplot, stylecounters, metrics, plt)

        util.ensure_dir(filename)
        plt.savefig(filename, dpi=150)
        log = logging.getLogger("pdfanalyze")
        log.debug("wrote %s" % filename)

    def plot_margins(self, subplots, margin_counters, metrics,
                     pagewidth, pageheight):
        for (idx, counterkey) in enumerate(sorted(margin_counters.keys())):
            # print("Making plot for %s" % counterkey)
            # leftmargin_even => left
            # topmargin => top
            plot = subplots[idx]
            series = list(margin_counters[counterkey].elements())
            size = pagewidth if "left" in counterkey or "right" in counterkey else pageheight
            # this is ridiculiously slow. Maybe ordinary bar charts
            # are faster?
            bins = plot.hist(series, bins=size, range=(0, size))
            plot.set_title(counterkey)
            for k, v in metrics.items():
                 # FIXME: How annotate parindent, 2col etc ?
                if counterkey == k: 
                    label = "%s=%s" % (k, v)  # leftmargin=102
                    # print("   plotting annotation %s" % label)
                    plot.annotate(label, xy=(v, 100),
                                  xytext=(v * 0.5, 100),
                                  arrowprops={'arrowstyle': '->'})

    def plot_styles(self, plot, stylecounter, metrics, plt):
        # do a additive vhist. FIXME: label those styles identified in
        # metrics
        stylenames = [style[0].replace("TimesNewRomanPS",
                                       "Times") + "@" + str(style[1]) for style,
                      count in stylecounter.most_common()]
        stylecounts = [count for style, count in stylecounter.most_common()]
        # need access to plt.
        plt.yticks(range(len(stylenames)), stylenames)
        plot.barh(range(len(stylenames)), stylecounts, log=True)
        plot.set_title("Font usage", fontdict={'fontsize': 8})
