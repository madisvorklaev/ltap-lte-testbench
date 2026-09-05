# 2026-09-02 11:22:47 by RouterOS 7.24.2
# software id = 4RKD-U3FV
#
# model = RB4011iGS+
# serial number = D4480CEA5BAB
/interface bridge add admin-mac=48:8F:5A:F3:2F:11 auto-mac=no comment=defconf name=bridge
/interface list add comment=defconf name=WAN
/interface list add comment=defconf name=LAN
/interface wireless security-profiles set [ find default=yes ] supplicant-identity=MikroTik
/ip pool add name=default-dhcp ranges=192.168.88.10-192.168.88.254
/routing table add fib name=elmo_rut_a
/routing table add fib name=elmo_rut_b
/disk settings set auto-media-interface=bridge auto-media-sharing=yes auto-smb-sharing=yes
/interface bridge port add bridge=bridge comment=defconf interface=ether4
/interface bridge port add bridge=bridge comment=defconf interface=ether5
/interface bridge port add bridge=bridge comment=defconf interface=ether6
/interface bridge port add bridge=bridge comment=defconf interface=ether7
/interface bridge port add bridge=bridge comment=defconf interface=ether8
/interface bridge port add bridge=bridge comment=defconf interface=ether9
/interface bridge port add bridge=bridge comment=defconf interface=ether10
/interface bridge port add bridge=bridge comment=defconf interface=sfp-sfpplus1
/interface bridge port add bridge=bridge comment="ELMO OpenClaw and iPerf host" interface=ether1
/ip neighbor discovery-settings set add-dns-entries=yes discover-interface-list=LAN
/interface list member add comment=defconf interface=bridge list=LAN
/interface list member add comment="ELMO RUTX12-A" interface=ether2 list=WAN
/interface list member add comment="ELMO RUTX12-B" interface=ether3 list=WAN
/ip address add address=192.168.88.1/24 comment=defconf interface=bridge network=192.168.88.0
/ip address add address=192.168.11.2/24 comment="ELMO toward RUTX12-A" interface=ether2 network=192.168.11.0
/ip address add address=192.168.12.2/24 comment="ELMO toward RUTX12-B" interface=ether3 network=192.168.12.0
/ip address add address=192.168.101.254/24 comment=ELMO-TEST-SOURCE-SUBNET interface=bridge network=192.168.101.0
/ip dhcp-client add comment=defconf disabled=yes interface=ether1 name=client1
/ip dhcp-server add add-dns-entries=yes address-pool=default-dhcp interface=bridge name=defconf
/ip dhcp-server network add address=192.168.88.0/24 comment=defconf dns-server=192.168.88.1 gateway=192.168.88.1
/ip dns set allow-remote-requests=yes
/ip dns static add address=192.168.88.1 comment=defconf name=router.lan type=A
/ip firewall filter add action=accept chain=input comment="defconf: accept established,related,untracked" connection-state=established,related,untracked
/ip firewall filter add action=drop chain=input comment="defconf: drop invalid" connection-state=invalid
/ip firewall filter add action=accept chain=input comment="defconf: accept ICMP" protocol=icmp
/ip firewall filter add action=accept chain=input comment="defconf: accept to local loopback (for CAPsMAN)" dst-address=127.0.0.1 in-interface=lo src-address=127.0.0.1
/ip firewall filter add action=drop chain=input comment="defconf: drop all not coming from LAN" in-interface-list=!LAN
/ip firewall filter add action=accept chain=forward comment="defconf: accept in ipsec policy" ipsec-policy=in,ipsec
/ip firewall filter add action=accept chain=forward comment="defconf: accept out ipsec policy" ipsec-policy=out,ipsec
/ip firewall filter add action=fasttrack-connection chain=forward comment="defconf: fasttrack" connection-state=established,related disabled=yes
/ip firewall filter add action=accept chain=forward comment="defconf: accept established,related, untracked" connection-state=established,related,untracked
/ip firewall filter add action=drop chain=forward comment="defconf: drop invalid" connection-state=invalid
/ip firewall filter add action=drop chain=forward comment="defconf: drop all from WAN not DSTNATed" connection-nat-state=!dstnat in-interface-list=WAN
/ip firewall mangle add action=passthrough chain=forward comment=ELMO-TEST-A-CORRECT out-interface=ether2 src-address=192.168.101.201
/ip firewall mangle add action=passthrough chain=forward comment=ELMO-TEST-A-CROSS out-interface=ether3 src-address=192.168.101.201
/ip firewall mangle add action=passthrough chain=forward comment=ELMO-TEST-B-CORRECT out-interface=ether3 src-address=192.168.101.202
/ip firewall mangle add action=passthrough chain=forward comment=ELMO-TEST-B-CROSS out-interface=ether2 src-address=192.168.101.202
/ip firewall nat add action=masquerade chain=srcnat comment="defconf: masquerade" ipsec-policy=out,none out-interface-list=WAN
/ip route add comment=ELMO-TEST-A-DEFAULT disabled=no distance=1 dst-address=0.0.0.0/0 gateway=192.168.11.1@main routing-table=elmo_rut_a
/ip route add comment=ELMO-TEST-B-DEFAULT disabled=no distance=1 dst-address=0.0.0.0/0 gateway=192.168.12.1@main routing-table=elmo_rut_b
/ipv6 firewall address-list add address=::/128 comment="defconf: unspecified address" list=bad_ipv6
/ipv6 firewall address-list add address=::1/128 comment="defconf: lo" list=bad_ipv6
/ipv6 firewall address-list add address=fec0::/10 comment="defconf: site-local" list=bad_ipv6
/ipv6 firewall address-list add address=::ffff:0.0.0.0/96 comment="defconf: ipv4-mapped" list=bad_ipv6
/ipv6 firewall address-list add address=::/96 comment="defconf: ipv4 compat" list=bad_ipv6
/ipv6 firewall address-list add address=100::/64 comment="defconf: discard only " list=bad_ipv6
/ipv6 firewall address-list add address=2001:db8::/32 comment="defconf: documentation" list=bad_ipv6
/ipv6 firewall address-list add address=2001:10::/28 comment="defconf: ORCHID" list=bad_ipv6
/ipv6 firewall address-list add address=3ffe::/16 comment="defconf: 6bone" list=bad_ipv6
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept established,related,untracked" connection-state=established,related,untracked
/ipv6 firewall filter add action=drop chain=input comment="defconf: drop invalid" connection-state=invalid
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept ICMPv6" protocol=icmpv6
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept UDP traceroute" dst-port=33434-33534 protocol=udp
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept DHCPv6-Client prefix delegation." dst-port=546 protocol=udp src-address=fe80::/10
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept IKE" dst-port=500,4500 protocol=udp
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept ipsec AH" protocol=ipsec-ah
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept ipsec ESP" protocol=ipsec-esp
/ipv6 firewall filter add action=accept chain=input comment="defconf: accept all that matches ipsec policy" ipsec-policy=in,ipsec
/ipv6 firewall filter add action=drop chain=input comment="defconf: drop everything else not coming from LAN" in-interface-list=!LAN
/ipv6 firewall filter add action=fasttrack-connection chain=forward comment="defconf: fasttrack6" connection-state=established,related
/ipv6 firewall filter add action=accept chain=forward comment="defconf: accept established,related,untracked" connection-state=established,related,untracked
/ipv6 firewall filter add action=drop chain=forward comment="defconf: drop invalid" connection-state=invalid
/ipv6 firewall filter add action=drop chain=forward comment="defconf: drop packets with bad src ipv6" src-address-list=bad_ipv6
/ipv6 firewall filter add action=drop chain=forward comment="defconf: drop packets with bad dst ipv6" dst-address-list=bad_ipv6
/ipv6 firewall filter add action=drop chain=forward comment="defconf: rfc4890 drop hop-limit=1" hop-limit=equal:1 protocol=icmpv6
/ipv6 firewall filter add action=accept chain=forward comment="defconf: accept ICMPv6" protocol=icmpv6
/ipv6 firewall filter add action=accept chain=forward comment="defconf: accept HIP" protocol=139
/ipv6 firewall filter add action=accept chain=forward comment="defconf: accept IKE" dst-port=500,4500 protocol=udp
/ipv6 firewall filter add action=accept chain=forward comment="defconf: accept ipsec AH" protocol=ipsec-ah
/ipv6 firewall filter add action=accept chain=forward comment="defconf: accept ipsec ESP" protocol=ipsec-esp
/ipv6 firewall filter add action=accept chain=forward comment="defconf: accept all that matches ipsec policy" ipsec-policy=in,ipsec
/ipv6 firewall filter add action=drop chain=forward comment="defconf: drop everything else not coming from LAN" in-interface-list=!LAN
/routing rule add action=lookup-only-in-table comment=ELMO-TEST-A-RULE src-address=192.168.101.201/32 table=elmo_rut_a
/routing rule add action=lookup-only-in-table comment=ELMO-TEST-B-RULE src-address=192.168.101.202/32 table=elmo_rut_b
/system identity set name=ELMO-RB4011-LAB
/system routerboard settings set enter-setup-on=delete-key
/tool mac-server set allowed-interface-list=LAN
/tool mac-server mac-winbox set allowed-interface-list=LAN
