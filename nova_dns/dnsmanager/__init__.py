#!/usr/bin/python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Nova DNS
#    Copyright (C) GridDynamics Openstack Core Team, GridDynamics
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as published by
#    the Free Software Foundation, either version 2.1 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re

from nova import flags
from nova.openstack.common import log as logging

from abc import ABCMeta, abstractmethod

LOG = logging.getLogger("nova_dns.dnsmanager")

nova_dns_dnsmanager_opts = [
    flags.cfg.IntOpt("dns_default_ttl", 
                     default=7200,
                     help="Default record ttl"),
    flags.cfg.StrOpt("dns_soa_primary", 
                     default="ns1",
                     help="Name server that will respond authoritatively for the domain"),
    flags.cfg.StrOpt("dns_soa_email", 
                     default="hostmaster",
                     help="Email address of the person responsible for this zone "),
    flags.cfg.IntOpt("dns_soa_refresh", 
                     default=10800,
                     help="The time when the slave will try to refresh the zone from the master"),
    flags.cfg.IntOpt("dns_soa_retry", 
                     default=3600,
                     help="time between retries if the slave fails to contact the master"),
    flags.cfg.IntOpt("dns_soa_expire", 
                     default=604800,
                     help="Indicates when the zone data is no longer authoritative")
]

record_types=set(('A', 'AAAA', 'MX', 'SOA', 'CNAME', 'PTR', 'SPF', 'SRV', 'TXT', 'NS',
          'AFSDB', 'CERT', 'DNSKEY', 'DS', 'HINFO', 'KEY', 'LOC', 'NAPTR', 'RP', 'RRSIG',
          'SSHFP'))

FLAGS = flags.FLAGS
FLAGS.register_opts(nova_dns_dnsmanager_opts)

class DNSManager:
    """abstract class"""
    __metaclass__ = ABCMeta

    @abstractmethod
    def list(self):
        """ should return list of DNSZone objects for all zones"""
        pass

    @abstractmethod
    def add(self, zone_name, soa):
        pass

    @abstractmethod
    def drop(self, zone_name, force=False):
        """ drop zone with all records. return True if was deleted """
        pass

    @abstractmethod
    def get_by_ip(self, ip):
	""" return DNSRecord object for ip. """
	pass

    @abstractmethod
    def get(self, zone_name):
        """ return DNSZone object for zone_name.
        If zone not exist, raise exception
         """
        pass

    @abstractmethod
    def drop_by_ip(self, ip):
        """ drop a record by IP
        Retunr True if record was deleted
        """
        pass

    @abstractmethod
    def init_host(self):
        """ Init Host
         """
        pass



class DNSZone:
    @abstractmethod
    def __init__(self, zone_name):
        pass
    @abstractmethod
    def drop(self):
        pass
    @abstractmethod
    def add(self, v):
        pass
    @abstractmethod
    def get(self, name, type=None):
        pass
    @abstractmethod
    def get_by_ip(self, name):
	pass
    @abstractmethod
    def set(self, name, type, content, priority, ttl):
        pass
    @abstractmethod
    def delete(self, name, type):
        pass

class DNSRecord:
    def __init__(self, name, type, content, priority=None, ttl=None):
        self.name=DNSRecord.normname(name)
        self.type=DNSRecord.normtype(type)
        self.content=content
        self.priority=int(priority) if priority else 0
        self.ttl=int(ttl) if ttl else FLAGS.dns_default_ttl
    @staticmethod
    def normtype(type):
        t=str(type).upper()
        if t not in record_types:
            raise ValueError("Incorrect type: " + type)
        return t
    @staticmethod
    def normname(n):
        name = str(n).lower()
        if name=="" or name=="*" or re.match(r'\A(?:[\w\d-]+\.)*(?:[\w\d-]+)\Z', name):
            return name
        else:
            raise ValueError("Incorrect DNS name: " + name)

class DNSSOARecord(DNSRecord):
    def __init__(self, primary=None, hostmaster=None, serial=None, refresh=None, retry=None, expire=None, ttl=None):
        self.primary=primary if primary else FLAGS.dns_soa_primary
        self.hostmaster=hostmaster if hostmaster else FLAGS.dns_soa_email
        self.serial=serial if serial else 0
        self.refresh=int(refresh) if refresh else FLAGS.dns_soa_refresh
        self.retry=int(retry) if retry else FLAGS.dns_soa_retry
        self.expire=int(expire) if expire else FLAGS.dns_soa_expire
        DNSRecord.__init__(self, '', 'SOA', '', None, ttl)

