# coding: utf-8
# vi:et:ts=8:

import logging

import oaipmh.common as oc
import oaipmh.metadata as om
import lxml.etree
from fn.uniform import range
from ckanext.oaipmh.cmdi_reader import CmdiReader
from ckanext.oaipmh.datacite_reader import DataCiteReader
from ckanext.oaipmh.oai_dc_reader import dc_metadata_reader

from . import importcore

xml_reader = importcore.generic_xml_metadata_reader
rdf_reader = importcore.generic_rdf_metadata_reader
log = logging.getLogger(__name__)


def ExceptReturn(exception, returns):
    def decorator(f):
        def call(*args, **kwargs):
            try:
                log.debug('call()')
                return f(*args, **kwargs)
            except exception as e:
                log.error('Exception occurred: %s' % e)
                return returns
        log.debug('decorator()')
        return call
    log.debug('ExceptReturn()')
    return decorator


def copy_element(source, dest, md, callback=None):
        '''Copy element in metadata dictionary from one key to another

        This function changes the metadata dictionary, md, by copying the
        value corresponding to key source to the value corresponding to
        the key dest.  It also copies all elements if it is an indexed
        element, and language information that pertains to the copied
        element.  The parameter callback, if given, is called with any
        element names formed (indexed or no).

        :param source: key to be copied
        :type source: string
        :param dest: key to copy to
        :type dest: string
        :param md: a metadata dictionary to update
        :type md: hash from string to any value (inout)
        :param callback: optional callback function, called with source,
                dest and their indexed versions
        :type callback: function of (string, string) -> None
        '''
        # Check if key exists in dictionary
        if source in md:
                md[dest] = md[source]
                copy_element(source + '/language', dest + '/language', md)
                copy_element(source + '/@lang', dest + '/language', md)
                copy_element(source + '/@xml:lang', dest + '/language', md)
                copy_element(source + '/@rdf:resource', dest, md)  # overwrites any possible element text

                # Call possible callback function
                if callback:
                    callback(source, dest, md)
                return

        count = md.get(source + '.count', 0)
        if not count:
            return

        # Add {dest}.count field to md
        md[dest + '.count'] = count
        for i in range(count):
                source_n = '%s.%d' % (source, i)
                dest_n = '%s.%d' % (dest, i)
                copy_element(source_n, dest_n, md, callback)


def person_attrs(source, dest, result):
    '''Callback for copying person attributes'''
    # TODO: here we could also fetch from ISNI/ORCID
    copy_element(source + '/foaf:name', dest + '/name', result)
    copy_element(source + '/foaf:mbox', dest + '/email', result)
    copy_element(source + '/foaf:phone', dest + '/phone', result)


def nrd_metadata_reader(xml):
        '''Read metadata in NRD schema

        This function takes NRD metadata as an lxml.etree.Element object,
        and returns the same metadata as a dictionary, with central TTA
        elements picked to format-independent keys.

        :param xml: RDF metadata as XML-encoded NRD
        :type xml: lxml.etree.Element instance
        :returns: a metadata dictionary
        :rtype: a hash from string to any value
        '''
        result = rdf_reader(xml).getMap()

        def document_attrs(source, dest, result):
                '''Callback for copying document attributes'''
                copy_element(source + '/dct:title', dest + '/title', result)
                copy_element(source + '/dct:identifier', dest, result)
                copy_element(source + '/dct:creator', dest + '/creator.0/name', result)
                copy_element(source + '/nrd:creator', dest + '/creator', result, person_attrs)
                copy_element(source + '/dct:description', dest + '/description', result)

        def funding_attrs(source, dest, result):
                '''Callback for copying project attributes'''
                copy_element(source + '/rev:arpfo:funds.0/arpfo:grantNumber', dest + '/fundingNumber', result)
                copy_element(source + '/rev:arpfo:funds.0/rev:arpfo:provides', dest + '/funder', result, person_attrs)

        def file_attrs(source, dest, result):
                '''Callback for copying manifestation attributes'''
                copy_element(source + '/dcat:mediaType', dest + '/mimetype', result)
                copy_element(source + '/fp:checksum.0/fp:checksumValue.0', dest + '/checksum.0', result)
                copy_element(source + '/fp:checksum.0/fp:generator.0', dest + '/checksum.0/algorithm', result)
                copy_element(source + '/dcat:byteSize', dest + '/size', result)

        mapping = [
            ('dataset', 'versionidentifier', None),
            ('dataset/nrd:continuityIdentifier', 'continuityidentifier', None),
            ('dataset/rev:foaf:primaryTopic.0/nrd:metadataIdentifier', 'metadata/identifier', None),
            ('dataset/rev:foaf:primaryTopic.0/nrd:metadataModified', 'metadata/modified', None),
            ('dataset/dct:title', 'title', None),
            ('dataset/nrd:modified', 'modified', None),
            ('dataset/nrd:rights', 'rights', None),
            ('dataset/nrd:language', 'language', None),
            ('dataset/nrd:owner', 'owner', person_attrs),
            ('dataset/nrd:creator', 'creator', person_attrs),
            ('dataset/nrd:distributor', 'distributor', person_attrs),
            ('dataset/nrd:contributor', 'contributor', person_attrs),
            ('dataset/nrd:subject', 'subject', None),  # fetch tags?
            ('dataset/nrd:producerProject', 'project', funding_attrs),
            ('dataset/dct:isPartOf', 'collection', document_attrs),
            ('dataset/dct:requires', 'requires', None),
            ('dataset/nrd:discipline', 'discipline', None),
            ('dataset/nrd:temporal', 'temporalcoverage', None),
            ('dataset/nrd:spatial', 'spatialcoverage', None),  # names?
            ('dataset/nrd:manifestation', 'resource', file_attrs),
            ('dataset/nrd:observationMatrix', 'variables', None),  # TODO
            ('dataset/nrd:usedByPublication', 'publication', document_attrs),
            ('dataset/dct:description', 'description', None),
        ]
        for source, dest, callback in mapping:
                copy_element(source, dest, result, callback)
        try:
                rights = lxml.etree.XML(result['rights'])
                rightsclass = rights.attrib['RIGHTSCATEGORY'].lower()
                result['rightsclass'] = rightsclass
                if rightsclass == 'licensed':
                        result['license'] = rights[0].text
                if rightsclass == 'contractual':
                        result['accessURL'] = rights[0].text
        except:
            pass
        return oc.Metadata(result)


def create_metadata_registry(harvest_type=None, service_url=None):
    '''Return new metadata registry with all common metadata readers

    The readers currently implemented are for metadataPrefixes
    oai_dc, nrd, rdf and xml.

    :returns: metadata registry instance
    :rtype: oaipmh.metadata.MetadataRegistry
    '''
    registry = om.MetadataRegistry()
    registry.registerReader('oai_dc', dc_metadata_reader(harvest_type or 'default'))
    registry.registerReader('cmdi0571', CmdiReader(service_url))
    registry.registerReader('oai_datacite3', DataCiteReader())
    registry.registerReader('nrd', nrd_metadata_reader)
    registry.registerReader('rdf', rdf_reader)
    registry.registerReader('xml', xml_reader)
    return registry
