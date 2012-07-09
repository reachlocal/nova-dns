
__version__ = "0.2.2"

try:
    from nova import flags

    nova_dns_opts = [
      flags.cfg.StrOpt("dns_manager", 
                       default="nova_dns.dnsmanager.powerdns.Manager",
                       help="DNS manager class"),
      flags.cfg.StrOpt("dns_listener", 
                        default="nova_dns.listener.simple.Listener",
                        help="Class to process AMQP messages"),
      flags.cfg.StrOpt("dns_api_paste_config", 
                       default="/etc/nova-dns/dns-api-paste.ini",
                       help="File name for the paste.deploy config for nova-dns api")
    ]

    FLAGS = flags.FLAGS
    FLAGS.register_opts(nova_dns_opts)

except:
    #make setup.py happy
    pass

