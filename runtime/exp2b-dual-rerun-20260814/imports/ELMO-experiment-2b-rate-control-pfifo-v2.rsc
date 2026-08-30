# ELMO Experiment 2b-B -- fixed-rate PFIFO reference, stationary lab test
# Version: 2.0 / 2026-08-13
#
# PURPOSE
#   Rate-control reference for the CAKE experiment.
#   It applies the SAME 5 Mbit/s HTB cap and the SAME test-packet selection
#   as the CAKE treatment, but uses a conventional 50-packet PFIFO leaf queue.
#
# WHY THIS CONDITION EXISTS
#   Comparing "no queue" directly with "CAKE + a 5M cap" confounds two changes:
#   lower LTE offered load and AQM. This PFIFO condition lets the experiment
#   determine whether CAKE adds value beyond static rate limiting alone.
#
#   This is a LAB EXPERIMENT, not a production recommendation.

:local shapeRate "5M"
:local testLte1Source "192.168.101.201/32"
:local testLte2Source "192.168.101.202/32"
:local packetMarkLte1 "elmo-exp2b-lte1"
:local packetMarkLte2 "elmo-exp2b-lte2"
:local queueTypeName "elmo-exp2b-pfifo"
:local queueTreeLte1 "ELMO-EXP2B-LTE1"
:local queueTreeLte2 "ELMO-EXP2B-LTE2"

:put "ELMO EXP2B-B: checking prerequisites"

:if ([:len [/interface lte find where name="lte1"]] = 0) do={
    :error "ELMO EXP2B-B: lte1 not found"
}
:if ([:len [/interface lte find where name="lte2"]] = 0) do={
    :error "ELMO EXP2B-B: lte2 not found"
}

:local lte1RouteRule [/ip firewall mangle find where comment="ELMO TEST: source via lte1"]
:local lte2RouteRule [/ip firewall mangle find where comment="ELMO TEST: source via lte2"]

:if ([:len $lte1RouteRule] != 1) do={
    :error "ELMO EXP2B-B: expected exactly one base rule 'ELMO TEST: source via lte1'"
}
:if ([:len $lte2RouteRule] != 1) do={
    :error "ELMO EXP2B-B: expected exactly one base rule 'ELMO TEST: source via lte2'"
}

:if ([:len [/ip firewall filter find where action=fasttrack-connection disabled=no]] > 0) do={
    :error "ELMO EXP2B-B: enabled FastTrack rule found. Stop and fix/verify base configuration first."
}

# Remove only prior Experiment 2b objects.
/queue tree remove [find where name="ELMO-EXP2B-LTE1"]
/queue tree remove [find where name="ELMO-EXP2B-LTE2"]
/queue type remove [find where name="elmo-exp2b-cake"]
/queue type remove [find where name="elmo-exp2b-pfifo"]
/ip firewall mangle remove [find where comment="ELMO EXP2B: test packet mark lte1"]
/ip firewall mangle remove [find where comment="ELMO EXP2B: test packet mark lte2"]

:if ([:len [/queue tree find where parent="lte1"]] > 0) do={
    /queue tree print detail where parent="lte1"
    :error "ELMO EXP2B-B: another queue tree already uses parent=lte1; do not stack experiments"
}
:if ([:len [/queue tree find where parent="lte2"]] > 0) do={
    /queue tree print detail where parent="lte2"
    :error "ELMO EXP2B-B: another queue tree already uses parent=lte2; do not stack experiments"
}

/ip firewall mangle add \
    chain=prerouting in-interface-list=LAN src-address=$testLte1Source \
    dst-address-type=!local action=mark-packet new-packet-mark=$packetMarkLte1 \
    passthrough=yes place-before=$lte1RouteRule \
    comment="ELMO EXP2B: test packet mark lte1"

/ip firewall mangle add \
    chain=prerouting in-interface-list=LAN src-address=$testLte2Source \
    dst-address-type=!local action=mark-packet new-packet-mark=$packetMarkLte2 \
    passthrough=yes place-before=$lte2RouteRule \
    comment="ELMO EXP2B: test packet mark lte2"

/queue type add name=$queueTypeName kind=pfifo pfifo-limit=50

/queue tree add \
    name=$queueTreeLte1 parent=lte1 packet-mark=$packetMarkLte1 \
    queue=$queueTypeName max-limit=$shapeRate

/queue tree add \
    name=$queueTreeLte2 parent=lte2 packet-mark=$packetMarkLte2 \
    queue=$queueTypeName max-limit=$shapeRate

:put ""
:put "ELMO EXP2B-B: PFIFO 5M rate-control reference installed."
:put "ELMO EXP2B-B: verify both queue trees are valid and counters increment."
:put ""

/queue type print detail where name="elmo-exp2b-pfifo"
/queue tree print stats detail where name="ELMO-EXP2B-LTE1"
/queue tree print stats detail where name="ELMO-EXP2B-LTE2"
/ip firewall mangle print stats detail where comment~"ELMO EXP2B:"
