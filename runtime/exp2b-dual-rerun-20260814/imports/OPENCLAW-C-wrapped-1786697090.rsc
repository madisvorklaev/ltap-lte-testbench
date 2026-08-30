:do {
    # ELMO Experiment 2b-C -- CAKE AQM, stationary lab test
    # Version: 2.0 / 2026-08-13
    #
    # PURPOSE
    #   Controlled CAKE treatment for the ELMO stationary LTE lab experiment.
    #   This file is ADDITIVE to the existing ELMO production+lab configuration.
    #   It does NOT change APNs, LTE bands, routing tables, NAT, or production
    #   video routing. It shapes only the reserved lab test sources:
    #       192.168.101.201 -> lte1
    #       192.168.101.202 -> lte2
    #
    # IMPORTANT
    #   - Intended for RouterOS 7.23.3+ with CAKE support.
    #   - The base source-routing rules must already exist.
    #   - FastTrack must already be disabled by the base ELMO config.
    #   - This is a LAB EXPERIMENT, not a production recommendation.
    #
    # EXPERIMENT DESIGN
    #   HTB max-limit=5M is intentionally identical to the companion PFIFO
    #   reference config. The only intended B-vs-C difference is leaf queue type:
    #       B = PFIFO at 5M
    #       C = CAKE at 5M
    #
    #   CAKE's own shaper is left unlimited (cake-bandwidth=0); HTB supplies the
    #   5M rate limit. Flow isolation and DiffServ are deliberately disabled for
    #   this first scientific test so sparse ping traffic is not preferentially
    #   isolated from the UDP stream. A later production-candidate test may use
    #   normal CAKE flow isolation after the basic AQM effect is established.
    
    :local shapeRate "5M"
    :local testLte1Source "192.168.101.201/32"
    :local testLte2Source "192.168.101.202/32"
    :local packetMarkLte1 "elmo-exp2b-lte1"
    :local packetMarkLte2 "elmo-exp2b-lte2"
    :local queueTypeName "elmo-exp2b-cake"
    :local queueTreeLte1 "ELMO-EXP2B-LTE1"
    :local queueTreeLte2 "ELMO-EXP2B-LTE2"
    
    :put "ELMO EXP2B-C: checking prerequisites"
    
    :if ([:len [/interface lte find where name="lte1"]] = 0) do={
        :error "ELMO EXP2B-C: lte1 not found"
    }
    :if ([:len [/interface lte find where name="lte2"]] = 0) do={
        :error "ELMO EXP2B-C: lte2 not found"
    }
    
    :local lte1RouteRule [/ip firewall mangle find where comment="ELMO TEST: source via lte1"]
    :local lte2RouteRule [/ip firewall mangle find where comment="ELMO TEST: source via lte2"]
    
    :if ([:len $lte1RouteRule] != 1) do={
        :error "ELMO EXP2B-C: expected exactly one base rule 'ELMO TEST: source via lte1'"
    }
    :if ([:len $lte2RouteRule] != 1) do={
        :error "ELMO EXP2B-C: expected exactly one base rule 'ELMO TEST: source via lte2'"
    }
    
    :if ([:len [/ip firewall filter find where action=fasttrack-connection disabled=no]] > 0) do={
        :error "ELMO EXP2B-C: enabled FastTrack rule found. Stop and fix/verify base configuration first."
    }
    
    # Remove only prior Experiment 2b objects.
    # Queue trees must be removed before their queue type.
    /queue tree remove [find where name="ELMO-EXP2B-LTE1"]
    /queue tree remove [find where name="ELMO-EXP2B-LTE2"]
    /queue type remove [find where name="elmo-exp2b-cake"]
    /queue type remove [find where name="elmo-exp2b-pfifo"]
    /ip firewall mangle remove [find where comment="ELMO EXP2B: test packet mark lte1"]
    /ip firewall mangle remove [find where comment="ELMO EXP2B: test packet mark lte2"]
    
    # Refuse to stack this experiment on an unknown LTE-parent queue.
    :if ([:len [/queue tree find where parent="lte1"]] > 0) do={
        /queue tree print detail where parent="lte1"
        :error "ELMO EXP2B-C: another queue tree already uses parent=lte1; do not stack experiments"
    }
    :if ([:len [/queue tree find where parent="lte2"]] > 0) do={
        /queue tree print detail where parent="lte2"
        :error "ELMO EXP2B-C: another queue tree already uses parent=lte2; do not stack experiments"
    }
    
    # Mark only the dedicated lab-source packets. These rules MUST run before the
    # base passthrough=no mark-routing rules.
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
    
    # CAKE is used as the leaf AQM only. HTB queue-tree max-limit supplies the
    # static 5M shaping rate. besteffort+flowblind intentionally avoid DSCP and
    # fair-queue isolation as extra variables in this first test.
    /queue type add \
        name=$queueTypeName kind=cake cake-bandwidth=0 \
        cake-autorate-ingress=no cake-diffserv=besteffort cake-flowmode=flowblind
    
    /queue tree add \
        name=$queueTreeLte1 parent=lte1 packet-mark=$packetMarkLte1 \
        queue=$queueTypeName max-limit=$shapeRate
    
    /queue tree add \
        name=$queueTreeLte2 parent=lte2 packet-mark=$packetMarkLte2 \
        queue=$queueTypeName max-limit=$shapeRate
    
    :put ""
    :put "ELMO EXP2B-C: CAKE treatment installed."
    :put "ELMO EXP2B-C: test sources only, HTB max-limit=5M per LTE path."
    :put "ELMO EXP2B-C: verify both queue trees are valid and counters increment."
    :put ""
    
    /queue type print detail where name="elmo-exp2b-cake"
    /queue tree print stats detail where name="ELMO-EXP2B-LTE1"
    /queue tree print stats detail where name="ELMO-EXP2B-LTE2"
    /ip firewall mangle print stats detail where comment~"ELMO EXP2B:"

}
