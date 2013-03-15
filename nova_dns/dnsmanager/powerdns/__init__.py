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

import time
import subprocess
import os
import os.path

from nova import flags
from nova.openstack.common import log as logging
from nova_dns.dnsmanager import DNSManager, DNSZone, DNSRecord, DNSSOARecord
from nova_dns.dnsmanager.powerdns.session import get_session
from nova_dns.dnsmanager.powerdns.models import Domains, Records
from sqlalchemy.sql import and_
LOG = logging.getLogger("nova_dns.dnsmanager.powerdns")

pdns_nova_dns_dnsmanager_opts = [
    flags.cfg.StrOpt("dns_powerdns_geomaps_dir", 
                     default="/var/lib/powerdns/nova/maps",
                     help="Default record ttl"),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(pdns_nova_dns_dnsmanager_opts)


models.register_models()

class Manager(DNSManager):
    def __init__(self):
        self.session=get_session()
    def list(self):
        return [name[0] for name in self.session.query(Domains.name).all()]
    def add(self, zone_name, soa={}):
        if zone_name in self.list():
            raise Exception('Zone already exists')
        zone_name=DNSRecord.normname(zone_name)
        self.session.add(Domains(name=zone_name, type="NATIVE"))
        self.session.flush()
        LOG.info("[%s]: Zone was added" % (zone_name))
        soa=DNSSOARecord(**soa)
        # PowerDNS-specific. TODO make this more pytonish - with objects
        # and bells
        soa.content=" ".join((str(f) for f in (soa.primary, soa.hostmaster, soa.serial,
            soa.refresh, soa.retry, soa.expire, soa.ttl)))
        PowerDNSZone(zone_name).add(soa)
        return "ok"
    def drop(self, zone_name, force=False):
        domains=self.session.query(Domains).filter(Domains.name.like('%'+zone_name)).all()
        if not domains:
            raise Exception('Zone not exists')
        elif len(domains)>1 and not force:
            raise Exception("Subzones exists: " + " ".join([d.name for d in domains]))
        for domain in domains:
            PowerDNSZone(domain.name).drop()
            self.session.delete(domain)
            LOG.info("[%s]: Zone was deleted" % (domain.name))
        self.session.flush()
        return "ok"
    def get(self, zone_name):
        if zone_name in self.list():
            return PowerDNSZone(zone_name)
        else:
            raise Exception('Zone does not exist')
    def get_by_ip(self, ip):
        return self.session.query(Records.name).filter(Records.content.like('%'+ip+'%')).all()
    def drop_by_ip(self, ip):
        q=self.session.query(Records).filter(Records.content==ip)

        if q.delete():
            LOG.info("Record with IP (%s) was deleted" %(ip))
            return True 
        else:
            raise Exception("No records was deleted")

    def init_host(self):
       pass

class PowerDNSZone(DNSZone):
    def __init__(self, zone_name):
        self.zone_name=zone_name
        self.session=get_session()
        domain=self.session.query(Domains).filter(Domains.name==zone_name).first()
        if not domain:
            raise Exception("Unknown zone: "+zone_name)
        self.domain_id=domain.id
    def get_soa(self):
        content=self._q(type="SOA", name='').first().content
        #content format is "primary hostmaster serial refresh retry expire ttl"
        #so we can magically pass it to consrtuctor
        return DNSSOARecord(*content.split())
    def drop(self):
        self._q().delete()
    def add(self, v):
        rec=Records()
        rec.domain_id=self.domain_id
        rec.name=rec.name=v.name+"."+self.zone_name if v.name else self.zone_name
        rec.name=DNSRecord.normname(rec.name)
        rec.type=v.type
        rec.content=v.content
        rec.ttl=v.ttl
        rec.prio=v.priority
        rec.change_date=int(time.time())
        self.session.add(rec)
        self.session.flush()
        LOG.info("[%s]: Record (%s, %s, '%s') was added" %
            (self.zone_name, rec.name, rec.type, rec.content))
        self._update_serial(rec.change_date)
        if v.name:
            top_level_zone=".".join(self.zone_name.split(".")[1:])
            file_name= FLAGS.dns_powerdns_geomaps_dir+ "/" + v.name  + "." + top_level_zone
            with open(file_name,"w") as f:
                f.write("$RECORD %s\n"%(v.name))
                f.write("$ORIGIN %s\n"%(top_level_zone))
                f.write("0   %s.external\n"%(v.name))
                f.write("900 %s.internal\n"%(v.name))
                f.flush()
                subprocess.call(["sudo","pdns_control","rediscover"])
        subprocess.call(['sudo','pdnssec','--config-dir=/etc/powerdns/pdnssec','rectify-zone',self.zone_name])
        return "ok"
    def get(self, name=None, type=None):
        res=[]
        for r in self._q(name, type).all():
            if r.type=='SOA':
                res.append(DNSSOARecord(*r.content.split()))
            else:
                res.append(DNSRecord(name=r.name, type=r.type, 
                    content=r.content, priority=r.prio, ttl=r.ttl))
        return res
    def set(self, name, type, content="", priority="", ttl=""):
        if type=='SOA':
            raise exception("Can't change SOA")
        rec=self._q(name, type).first()
        if not rec:
            raise Exception("Not found record (%s, %s)" % (name, type))
        if content:
            rec.content=content
        if ttl:
            rec.ttl=ttl
        if priority:
            rec.prio=priority
        rec.change_date=int(time.time())
        self.session.merge(rec)
        self.session.flush()
        self._update_serial(rec.change_date)
        LOG.info("[%s]: Record (%s, %s) was changed" % 
            (self.zone_name, rec.name, rec.type))
        return "ok"
    def delete(self, name, type=None):
        if self._q(name, type).delete():
            LOG.info("[%s]: Record (%s, %s) was deleted" % (self.zone_name, name, type))
            file_name= FLAGS.dns_powerdns_geomaps_dir+ "/" + name + "." + ".".join(self.zone_name.split(".")[1:]) 
            LOG.debug("Geomap file to delte: %s"%(file_name))
            if os.path.isfile(file_name):
                os.remove(file_name)
                subprocess.call(["sudo","pdns_control","rediscover"])
            return "ok"
        else:
            raise Exception("No records was deleted")
    def _update_serial(self, change_date):
        #TODO change to get_soa
        soa=self._q('', 'SOA').first()
        v=soa.content.split()
        #TODO change this to ordinar set()
        v[2]=change_date
        content=" ".join((str(f) for f in v))
        #FIXME should change_date for SOA be changed here ?
        soa.update({"content":content, "change_date":change_date})
        self.session.flush()
    def _q(self, name=None, type=None):
        q=self.session.query(Records).filter(Records.domain_id==self.domain_id)
	if type:
            q=q.filter(Records.type==DNSRecord.normtype(type))
        if name is None:
            return q
        fqdn=name+"."+self.zone_name if name else self.zone_name
        return q.filter(Records.name==fqdn)
