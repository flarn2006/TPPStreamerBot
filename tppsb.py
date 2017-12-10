#!/usr/bin/python

import sys
import re
import thread
import urllib
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

adminIrcNames = ['flarn2006', 'deadinsky']

updaterId = '102szrk71dw9r' # Main updater ID, for the current run or intermission.
updaterId2 = 'z0xcggm226qa' # Secondary updater ID, for mods who talk about other things a lot.
updaterIdTest = 'ty0ak5tjb4fq' # Test updater ID, used in test mode.

modList = ['twitchplayspokemon', 'aissurtievos'] # People whose messages are (almost) always worth posting to the updater.
modList2 = ['projectrevotpp', 'felkcraft'] # Only post these ones to the secondary updater.

testMode = 0 # 0) Normal mode
             # 1) Run normally, but post to test updater
			 # 2) Test mode - read messages from console instead of Twitch chat

# Messages matching any of these regular expressions will be completely ignored.
msgRejectPatterns = [
	re.compile('^!'), # Commands beginning with '!' (e.g. '!bet')
	re.compile('^_mode '), # Streamer has used this before to manually activate anarchy/democracy.
	re.compile('^(?:(?:[abxylrnews]|up|down|left|right|start|select|home|wait|anarchy|democracy|\\d{1,3},\\d{1,3}|move|switch|run|item[0-9]+(p[1-6](m[1-4])?))[0-9]*\\+?)+$', re.I), # Inputs - see http://regex101.com/ for help.
	re.compile('https:\/\/(?:www\.)?twitch\.tv\/tankturntactics')] # DatSheffy no spam

# End configurable parameters

prevMsgs = {}
prevMsgTimes = {}
displayNames = {}
ircNames = {}

if len(sys.argv) >= 2:
	if sys.argv[1] == '-t':
		testMode = 2
	elif sys.argv[1] == '-T':
		testMode = 1

if testMode > 0:
	updaterId = updaterIdTest
	updaterId2 = updaterIdTest
	modList.append(adminIrcNames[0]) # treat me as a streamer for easier testing

reddit = praw.Reddit(
	user_agent = 'TPPStreamerBot, by /u/flarn2006',
	client_id = identity['reddit_client_id'],
	client_secret = identity['reddit_client_secret'],
	username = identity['reddit_username'],
	password = identity['reddit_password'])

mentionedUserRegex = re.compile('^@([^.,:\\s]+)')
ircNameRegex = re.compile('^[A-Za-z0-9_]+$')

def getDisplayName(username):
	if username in displayNames:
		return displayNames[username]
	else:
		headers = {'Client-ID':identity['twitch_client_id'], 'Accept':'application/vnd.twitchtv.v3+json'}
		try:
			req = requests.get('https://api.twitch.tv/kraken/users/'+urllib.quote(username), headers=headers)
			dn = req.json()[u'display_name']
			displayNames[username] = dn
			ircNames[dn.lower()] = username
			return dn
		except Exception as ex:
			print '\x1b[1;31m[!] Error getting display name for {}\x1b[m'.format(username)
			return username

def getDisplayNameForUpdater(username):
	dn = getDisplayName(username)
	if dn.lower() != username.lower():
		return u'{} ({})'.format(dn, username)
	else:
		return dn

def getIrcName(displayname):
	if ircNameRegex.match(displayname):
		# This is a valid Twitch/IRC name on its own. No need to look it up.
		return displayname.lower()
	elif displayname in ircNames:
		# This is a recognized display name. Return its associated username.
		return ircNames[displayname]
	else:
		# Neither a valid Twitch name, nor a recognized display name. Return an empty string to mean no match.
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
		print '\x1b[0;37m-> \x1b[1;30m{}\x1b[m'.format(msg.encode('utf-8'))
	else:
		print '\x1b[1;36m-> \x1b[0;36m{}\x1b[m'.format(msg.encode('utf-8'))
	
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
		return getIrcName(match.group(1).lower())
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

		# Aissurtievos only wants messages beginning with a ` to be posted
		if user == 'aissurtievos' and not msg.startswith('`'):
			upd = ''
		
		if upd != '':
			# Message is from a monitored user.
			# First, see if the message is a reply to another user, so we can pull their message.
			mentionedUser = findUsernameInMsg(msg)
			
			if mentionedUser != '' and mentionedUser in prevMsgs and mentionedUser not in modList:
				# We've got a match! But let's make sure the message was posted recently.
				if datetime.now() - prevMsgTimes[mentionedUser] > timedelta(0, 300):
					# Looks like it wasn't. Let's remove it from the list and forget about it.
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
		
		# Add the message to the previous messages list.
		prevMsgs[user] = msg
		prevMsgTimes[user] = datetime.now()
		dn = getDisplayName(user)
		prevMsgs[dn] = msg
		prevMsgTimes[dn] = prevMsgTimes[user]

def handleWhisper(user, msg):
	global updaterId
	cmd = msg.split(u' ')
	cmd[0] = cmd[0].lower()

	if cmd[0] == 'lastmsg':
		try:
			cmd[1] = cmd[1].lower()
			if cmd[1] in prevMsgs:
				username = cmd[1]
			elif getDisplayName(cmd[1]) in prevMsgs:
				username = getDisplayName(cmd[1])
			else:
				return u"{} didn't say anything recently.".format(cmd[1])
			return u'[{} ago] {}: {}'.format(datetime.now()-prevMsgTimes[cmd[1]], getDisplayName(cmd[1]), prevMsgs[cmd[1]])
		except IndexError:
			return 'Usage: lastmsg <username>'
	elif cmd[0] == 'update':
		if user in adminIrcNames:
			text = unicode.join(u' ', cmd[1:])
			if text:
				postUpdate(updaterId, text)
				return 'Update posted to https://reddit.com/live/' + updaterId
			else:
				return 'Usage: update <text>'
		else:
			return 'Sorry, you do not have permission to use this command.'
	elif cmd[0] == 'setfeed':
		if user in adminIrcNames:
			try:
				if '/' in cmd[1]:
					return 'Try again with just the part after the slash, not the whole URL.'
				updaterId = cmd[1]
				return u'Moved to https://reddit.com/live/{}.\nPlease use the "update" command to test.'.format(updaterId)
			except IndexError:
				return 'Usage: setfeed <updater id>'
		else:
			return 'Sorry, you do not have permission to use this command.'
	elif cmd[0] == 'getfeed':
		return u'Currently posting to https://reddit.com/live/{}.'.format(updaterId)
	elif cmd[0] == 'help':
		return 'TPPStreamerBot, by /u/flarn2006\n\
		lastmsg <user> - Check the last thing said by a user\n\
		getfeed - Get the URL of the updater currently being posted to\n\
		setfeed <id> - Set the ID of the updater to post to (admin only)\n\
		update <text> - Posts a message to the live updater (admin only)'
	else:
		return u'Unrecognized command "{}"'.format(cmd[0])

def send_whisper(user, msg):
	global bot
	if msg != '':
		print u'\x1b[1;32m[W] {} <- \x1b[0;32m{}\x1b[m'.format(user, msg)
		for m in msg.split('\n'):
			bot.connection.privmsg('jtv', u'/w {} {}'.format(user, m)[:511])

class IrcWatcher(irc.bot.SingleServerIRCBot):
	firstMsg = False

	def __init__(self):
		server = irc.bot.ServerSpec('irc.chat.twitch.tv', 6667, identity['twitch_irc_oauth'])
		print '\x1b[1;33mConnecting to Twitch chat...\x1b[m'
		irc.bot.SingleServerIRCBot.__init__(self, [server], identity['twitch_irc_nick'], identity['twitch_irc_nick'])
	
	def on_welcome(self, server, event):
		server.cap('REQ', 'twitch.tv/commands')
		print '\x1b[1;33mJoining TPP channel...\x1b[m'
		server.join('#twitchplayspokemon')
		print '\x1b[1;32mNow monitoring chat.\x1b[m'
		self.firstMsg = True
	
	def on_pubmsg(self, server, event):
		if self.firstMsg:
			print '\x1b[1;32mFirst message received.\x1b[m'
			self.firstMsg = False
		handleMsg(event.source.nick, event.arguments[0])
	
	def on_whisper(self, server, event):
		print u'\x1b[1;33m[W] {}:\x1b[0;33m {}\x1b[m'.format(event.source.nick, event.arguments[0])
		try:
			reply = handleWhisper(event.source.nick, event.arguments[0])
			send_whisper(event.source.nick, reply)
		except Exception as ex:
			print u'\x1b[1;31mError processing whisper: \x1b[0;31m{}\x1b[m'.format(ex)

# Main loop begins here.

print '\x1b[1;34m * * * * * * * * * * * * * * * * *\x1b[m'
print '\x1b[1;34m* TPPStreamerBot, by /u/flarn2006 *\x1b[m'
print '\x1b[1;34m * * * * * * * * * * * * * * * * *\x1b[m'

if testMode == 2:
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
	# Connect to Twitch chat and read messages from there.
	try:
		bot = IrcWatcher()
		bot.start()
	except KeyboardInterrupt:
		print '\x1b[1;34mExiting.\x1b[m'
