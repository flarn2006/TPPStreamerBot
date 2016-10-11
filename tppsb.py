#!/usr/bin/python

import sys
import re
from time import sleep
from datetime import datetime, timedelta
import requests
import praw
from prawcore.exceptions import *
import irc.bot

# Begin configurable parameters

identity = { # Make sure to set these if they aren't already!
    'reddit_client_id':     '',
    'reddit_client_secret': '',
    'reddit_username':      '',
    'reddit_password':      '',
    'twitch_client_id':     '',
    'twitch_irc_nick':      '',
    'twitch_irc_oauth':     ''}

updaterId = 'xkrzrxrcl3ru' # Main updater ID, for the current run or intermission.
updaterId2 = 'uerqm64a940j' # Secondary updater ID, for mods who talk about other things a lot.
updaterIdTest = 'ty0ak5tjb4fq' # Test updater ID, used in test mode.

modList = ['twitchplayspokemon'] # People whose messages are (almost) always worth posting to the updater.
modList2 = ['projectrevotpp', 'felkcraft'] # Only post these ones to the secondary updater.

testMode = False # Set to True to enter messages manually.

# Messages matching any of these regular expressions will be completely ignored.
msgRejectPatterns = [
	re.compile('^!'), # Commands beginning with '!' (e.g. '!bet')
	re.compile('^_mode '), # Streamer has used this before to manually activate anarchy/democracy.
	re.compile('^(?:(?:[abxylr]|up|down|left|right|start|select|home|wait|anarchy|democracy|\\d{1,3},\\d{1,3}|move|switch|run|item[0-9]+(p[1-6](m[1-4])?))[0-9]*\\+?)+$')] # Inputs - see http://regex101.com/ for help.

# End configurable parameters

prevMsgs = {}
prevMsgTimes = {}
displayNames = {}
ircNames = {}

if len(sys.argv) >= 2:
	if sys.argv[1] == '-t':
		testMode = True

if testMode:
	# Let's not post fake test messages to the real updater.
	updaterId = updaterIdTest
	updaterId2 = updaterIdTest

reddit = praw.Reddit(
	user_agent = 'TPPStreamerBot, by /u/flarn2006',
	client_id = identity['reddit_client_id'],
	client_secret = identity['reddit_client_secret'],
	username = identity['reddit_username'],
	password = identity['reddit_password'])

mentionedUserRegex = re.compile('^@([^.,:\\s]+)')

def getDisplayName(username):
	if username in displayNames:
		return displayNames[username]
	else:
		headers = {'Client-ID':identity['twitch_client_id'], 'Accept':'application/vnd.twitchtv.v3+json'}
		try:
			req = requests.get('https://api.twitch.tv/kraken/users/'+username, headers=headers)
			dn = req.json()[u'display_name']
			displayNames[username] = dn
			ircNames[dn.lower()] = username
			return dn
		except Exception as ex:
			print '\x1b[1;31m[!] Error getting display name for {}: \x1b[0;31m{}\x1b[m'.format(username, ex)
			return username

def getDisplayNameForUpdater(username):
	dn = getDisplayName(username)
	if dn.lower() != username.lower():
		return u'{} ({})'.format(dn, username)
	else:
		return dn

def getIrcName(displayname):
	if displayname in ircNames:
		return ircNames[displayname]
	else:
		return ''

def isMsgImportant(msg):
	for r in msgRejectPatterns:
		if r.search(msg):
			return False
	return True

def escapeMarkdown(text):
	result = ''
	for c in text:
		if c in '\\*[]`^':
			result += '\\'
		result += c
	return result

def postUpdate(updater, msg):
	if updater == updaterId2:
		print '\x1b[0;37m-> \x1b[1;30m{}\x1b[m'.format(msg)
	else:
		print '\x1b[1;36m-> \x1b[0;36m{}\x1b[m'.format(msg)
	
	for i in xrange(10):
		try:
			reddit.request('POST', '/api/live/{}/update'.format(updater), {'api_type':'json', 'body':escapeMarkdown(msg)})
			break
		except RequestException as ex:
			print '\x1b[1;31m[!] ({}/10) Error sending request:\x1b[0;31m {}\x1b[m'.format(i+1, ex)
			sleep(1)
		except Forbidden:
			print "\x1b[1;31m[!] 403 FORBIDDEN: \x1b[0;31mDon't forget to accept the invitation!\x1b[m"
			break

def findUsernameInMsg(msg):
	match = mentionedUserRegex.match(msg)
	if match:
		return match.group(1).lower()
	else:
		return ''

def handleMsg(user, msg):
	if isMsgImportant(msg):
		# Determine which updater, if any, this message should be posted to.
		upd = ''
		if user in modList:
			upd = updaterId
		elif user in modList2:
			upd = updaterId2
		
		if upd != '':
			# Message is from a monitored user.
			# First, see if the message is a reply to another user, so we can pull their message.
			mentionedUser = getIrcName(findUsernameInMsg(msg))
			
			if mentionedUser != '' and mentionedUser in prevMsgs:
				# We've got a match! But let's make sure the message was posted recently.
				if datetime.now() - prevMsgTimes[mentionedUser] > timedelta(0, 300):
					# Looks like it wasn't. Let's remove it from the list and forget about it.
					prevMsgs.pop(mentionedUser)
					prevMsgTimes.pop(mentionedUser)
					mentionedUser = ''
			else:
				# Nope, no match. Either nobody was mentioned or we have no message stored from them.
				mentionedUser = ''
	
			if mentionedUser == '':
				# Standard format update
				postUpdate(upd, u'[Streamer] {}: {}'.format(getDisplayName(user), msg))
			else:
				# Update including message from other user
				postUpdate(upd, u'[Streamer] {}: {}\n\n{}: {}'.format(getDisplayNameForUpdater(mentionedUser), prevMsgs[mentionedUser], getDisplayName(user), msg))
		else:
			# Message isn't from a monitored user, but still add it to the previous messages list.
			prevMsgs[user] = msg
			prevMsgTimes[user] = datetime.now()
			dn = getDisplayName(user)
			prevMsgs[dn] = msg
			prevMsgTimes[dn] = prevMsgTimes[user]

class IrcWatcher(irc.bot.SingleServerIRCBot):
	firstMsg = False

	def __init__(self):
		server = irc.bot.ServerSpec('irc.twitch.tv', 6667, identity['twitch_irc_oauth'])
		print '\x1b[1;33mConnecting to Twitch chat...\x1b[m'
		irc.bot.SingleServerIRCBot.__init__(self, [server], identity['twitch_irc_nick'], identity['twitch_irc_nick'])
	
	def on_welcome(self, server, event):
		print '\x1b[1;33mJoining TPP channel...\x1b[m'
		server.join('#twitchplayspokemon')
		print '\x1b[1;32mNow monitoring chat.\x1b[m'
		self.firstMsg = True
	
	def on_pubmsg(self, server, event):
		if self.firstMsg:
			print '\x1b[1;32mFirst message received.\x1b[m'
			self.firstMsg = False
		handleMsg(event.source.nick, event.arguments[0])

# Main loop begins here.

print '\x1b[1;34m * * * * * * * * * * * * * * * * *\x1b[m'
print '\x1b[1;34m* TPPStreamerBot, by /u/flarn2006 *\x1b[m'
print '\x1b[1;34m * * * * * * * * * * * * * * * * *\x1b[m'

if testMode:
	# Test mode is active. Get test messages from the console instead of from unreliable Twitch chat.
	print '\x1b[1;35mRunning in test mode. Type "exit" when done.'
	
	while True:
		user = raw_input('\x1b[1;35mUser: \x1b[0;35m')
		if user == 'exit':
			break

		msg = raw_input('\x1b[1;35mMsg:  \x1b[0;35m')
		if msg == 'exit':
			break
		
		handleMsg(user, msg)
		print
	
	print '\x1b[m'
else:
	# We're running in production. Connect to Twitch chat and read messages from there.
	try:
		IrcWatcher().start()
	except KeyboardInterrupt:
		print '\x1b[1;34mExiting.\x1b[m'
