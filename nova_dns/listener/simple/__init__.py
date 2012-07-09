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

"""Simple listener:
- doesn't sync state with dns after restart
- stateless"""

import time
import eventlet

from nova import log as logging
from nova import utils
from nova import flags

from nova.db.sqlalchemy.session import get_engine

from nova_dns.dnsmanager import DNSRecord
from nova_dns.listener import AMQPListener
from nova_dns import auth

import netaddr

LOG = logging.getLogger("nova_dns.listener.simple")
SLEEP = 60 

AUTH = auth.AUTH

#TODO make own zone for every instance
nova_dns_lis_simple = [
    flags.cfg.ListOpt("dns_ns", 
                      default=["ns1:127.0.0.1"], 
                      help="Name servers, in format ns1:ip1, ns2:ip2"),
    flags.cfg.BoolOpt('dns_ptr', 
                      default=False, 
                      help='Manage PTR records'),
    flags.cfg.BoolOpt('dns_use_tenant_zone',
                      default=True,
                      help="Create a zone per tenant"),
    flags.cfg.ListOpt('dns_ptr_zones', 
                      default="", 
                      help="Classless delegation networks in format ip_addr/network")
]

FLAGS = flags.FLAGS
FLAGS.register_opts(nova_dns_lis_simple)

class Listener(AMQPListener):
    def __init__(self):
        self.pending={}
        LOG.info("Connecting to database @ %s"%(FLAGS.sql_connection))
        self.conn=get_engine()
        dnsmanager_class=utils.import_class(FLAGS.dns_manager);
        self.dnsmanager=dnsmanager_class()
        self.eventlet = eventlet.spawn(self._pollip)

    def event(self, e):
        method = e.get("method", "<unknown>")
        uuid = e["args"].get("instance_uuid", None)
        if method=="run_instance":
            LOG.info("Run instance %s. Waiting on assing ip address" % (str(uuid),))
            self.pending[uuid]=1
        elif method=="terminate_instance":
            if self.pending.has_key(uuid): del self.pending[uuid]
            rec = self.conn.execute("select hostname, project_id "+
                "from instances where uuid=%s", uuid).first()
            if not rec:
                LOG.error('Unknown uuid: '+str(uuid))
            else:
                try:
                    LOG.info("Instance %s hostname '%s' was terminated" %
                        (uuid, rec.hostname))
                    #TODO check if record was added/changed by admin
                    if (FLAGS.dns_use_tenant_zone):
                        zonename = AUTH.tenant2zonename(rec.project_id)
                    else:
                        zonename = FLAGS.dns_zone
                    zone=self.dnsmanager.get(zonename)
                    if FLAGS.dns_ptr:
                        ip = zone.get(rec.hostname, 'A')[0].content
                        (ptr_zonename, octet) = self.ip2zone(ip)
                        self.dnsmanager.get(ptr_zonename).delete(str(octet), 'PTR')
                    zone.delete(rec.hostname, 'A')
                except:
                    pass
        else:
            LOG.debug("Skip message with method: "+method)
    def _pollip(self):
        while True:
            time.sleep(SLEEP)
            if not len(self.pending):
                continue
            #TODO change select to i.id in ( pendings ) to speed up
            for r in self.conn.execute("""
                select i.hostname, i.uuid, i.project_id, f.address
                from instances i, fixed_ips f
                where i.id=f.instance_id"""):
                LOG.debug("Processing Record with id %s"%(r.uuid))
                if r.uuid not in self.pending: continue
                LOG.info("Instance %s hostname %s adding ip %s" %
                    (r.uuid, r.hostname, r.address))
                zones_list=self.dnsmanager.list()
                if FLAGS.dns_zone not in zones_list:
                    #Lazy create main zone and populate by ns
                    self._add_zone(FLAGS.dns_zone)
                if (FLAGS.dns_use_tenant_zone):
                    zonename = AUTH.tenant2zonename(r.project_id)
                    if zonename not in zones_list:
                        self._add_zone(zonename)
                else:
                    zonename = FLAGS.dns_zone
                try:
                    self.dnsmanager.get(zonename).add(
                        DNSRecord(name=r.hostname, type='A', content=r.address))
                    del self.pending[r.uuid]
                except ValueError as e:
                    LOG.warn(str(e))
                except:
                    pass
                if FLAGS.dns_ptr:
                    (ptr_zonename, octet) = self.ip2zone(r.address)
                    if ptr_zonename not in zones_list:
                        self._add_zone(ptr_zonename)
                    self.dnsmanager.get(ptr_zonename).add(DNSRecord(name=octet, 
                        type='PTR', content=r.hostname+'.'+zonename))

    def _add_zone(self, name):
        try:
            self.dnsmanager.add(name)
            zone=self.dnsmanager.get(name)
            for ns in FLAGS.dns_ns:
                (name,content)=ns.split(':',2)
                zone.add(DNSRecord(name=name, type="NS", content=content))
        except ValueError as e:
            LOG.warn(str(e))
        except:
            #TODO add exception ZoneExists and pass only it
            pass

    def ip2zone(self, ip):
        #TODO check /cidr >= 24
        addr = netaddr.IPAddress(ip) 
        for zone in FLAGS.dns_ptr_zones: 
            #TODO prepare netaddr one time on service start
            zoneaddr = netaddr.IPNetwork(zone)
            if addr not in zoneaddr:
                continue
            cidr = str(zoneaddr.cidr).split('/')[1]
            w = zoneaddr.cidr.ip.words
            return ("%s-%s.%s.%s.%s.in-addr.arpa" % 
                (w[3], cidr, w[2], w[1], w[0]), addr.words[-1])
        w = addr.words
        return ("%s.%s.%s.in-addr.arpa" % (w[2], w[1], w[0]), w[3])
