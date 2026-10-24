#!/bin/sh
# Can the game sign in? Exit 0 if so, 1 if it would be offline.
#
# Asked before Prism is started, because Prism's own answer costs a desktop.
# Measured in a network namespace with no route: Prism fails to refresh the
# Microsoft token in 0.13s and then opens a full-screen "Choose your offline
# mode player name" window — and the boot screen, which sits above every
# window, hides it until its 90s timeout. That is the minute and a half a
# no-wifi login spent looking stuck. Nothing was slow; something was waiting.
#
# So the launcher decides first and hands Prism `--offline <name>`, which is
# what pressing OK on that window does. Being wrong here is cheap in one
# direction only: a false "offline" costs a skin for one session, while a
# false "online" costs the prompt — so anything that is not a clear yes is no.
#
#   online.sh && echo online
#
# Never slower than a few seconds, and nearly free when the answer is known:
#
#   NetworkManager says connected, with full connectivity   ~20ms, no probe
#   NetworkManager says disconnected or asleep              ~20ms, no probe
#   NetworkManager is still connecting                      waits up to 10s
#   anything else, or no NetworkManager                     probe, up to 5s
#
# "full" is worth trusting because Arch ships NetworkManager with a real
# connectivity check (`ping.archlinux.org`, /usr/lib/NetworkManager/conf.d/
# 20-connectivity.conf), so it means the internet answered, not merely that
# there is a route. Measured on this machine: wifi reached CONNECTED_GLOBAL
# ten seconds before the GDM login, so the first row is the usual one.

set -u

# Microsoft's sign-in host: the first thing Prism asks, so the thing that has
# to answer. Any HTTP reply counts — 302 is what it gives — and a captive
# portal fails the TLS handshake, which is the right answer for it too.
probe=https://login.microsoftonline.com/

reach() {
	command -v curl >/dev/null 2>&1 || return 0   # cannot tell; let Prism try
	curl -s -o /dev/null --connect-timeout 3 -m 5 "$probe"
}

if ! command -v nmcli >/dev/null 2>&1; then
	reach
	exit
fi

state=$(nmcli -t -f STATE general 2>/dev/null)
case "$state" in
connecting)
	# A login fast enough to beat the wifi. nm-online returns the moment a
	# connection is up, so this costs only the wait it has to.
	nm-online -q -t 10 >/dev/null 2>&1 || exit 1
	state=$(nmcli -t -f STATE general 2>/dev/null)
	;;
esac

case "$state" in
disconnected | asleep | disconnecting)
	exit 1
	;;
connected)
	# CONNECTED_SITE turns into CONNECTED_GLOBAL a few hundred ms after the
	# link comes up (0.28s this morning), so a "limited" here may only be
	# early. That is the case the probe is for.
	[ "$(nmcli -t networking connectivity 2>/dev/null)" = full ] && exit 0
	reach
	;;
*)
	# "connected (site only)", "connected (local only)", or NetworkManager not
	# running at all. Ask the internet itself.
	reach
	;;
esac
