<?xml version="1.0" encoding="utf-8"?>
<!--
Note: this template expects XHTML1.1, outputs HTML5

It's a generic template for any kind of content
-->
<xsl:stylesheet version="1.0"
		xmlns:atom="http://www.w3.org/2005/Atom"
		xmlns:xhtml="http://www.w3.org/1999/xhtml"
		xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
		xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
		xmlns:dcterms="http://purl.org/dc/terms/"
		xmlns:rinfo="http://rinfo.lagrummet.se/taxo/2007/09/rinfo/pub#"
		xmlns:rinfoex="http://lagen.nu/terms#"
		xml:space="preserve"
		exclude-result-prefixes="xhtml rdf atom">

  <xsl:import href="uri.xsl"/>
  <xsl:include href="base.xsl"/>

  <!-- Implementations of templates called by base.xsl -->
  <xsl:template name="headtitle"><xsl:value-of select="//xhtml:title"/></xsl:template>
  <xsl:template name="metarobots"/>
  <xsl:template name="linkalternate"/>
  <xsl:template name="headmetadata"/>
  <xsl:template name="bodyclass">frontpage</xsl:template>
  <xsl:template name="pagetitle"/>
  <xsl:param name="dyntoc" select="false()"/>
  <xsl:param name="fixedtoc" select="true()"/>
  <xsl:param name="content-under-pagetitle" select="false()"/>
      
  <xsl:template match="xhtml:a">
    <xsl:call-template name="link"/>
  </xsl:template>

  <xsl:template match="xhtml:body/xhtml:div">
    <div class="section-wrapper" id="{@id}">
      <xsl:apply-templates/>
    </div>
  </xsl:template>

  <!-- default template: translate everything from whatever namespace
       it's in (usually the XHTML1.1 NS) into the default namespace
       -->
  <xsl:template match="*">
    <xsl:element name="{local-name(.)}"><xsl:apply-templates select="node()"/></xsl:element>
  </xsl:template>


  <!-- toc handling for atom feeds -->
  <xsl:template match="xhtml:div" mode="toc">
    <xsl:if test="$feedfile">
      <xsl:for-each select="document($feedfile)/atom:feed/atom:entry">
	<li>
	  <a href="{atom:id}"><xsl:value-of select="atom:title"/></a>
	  <ul><li>
	    <small><xsl:value-of select="substring(atom:published, 1, 10)"/></small>
	    <xsl:value-of select="atom:summary" disable-output-escaping="yes"/>
	  </li></ul>
	</li>
      </xsl:for-each>
    </xsl:if>
  </xsl:template>

  <!-- default toc handling (do nothing) -->
  <xsl:template match="@*|node()" mode="toc"/>

</xsl:stylesheet>

