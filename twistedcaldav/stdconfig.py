##
# Copyright (c) 2005-2009 Apple Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##

import os
import copy
import re

from twisted.web2.dav import davxml
from twisted.web2.dav.resource import TwistedACLInheritable

from twext.python.plistlib import readPlist

from twistedcaldav.config import (
    ConfigProvider, ConfigurationError, config, _mergeData, )
from twistedcaldav.log import (
    Logger, clearLogLevels, setLogLevelForNamespace, InvalidLogLevelError, )
from twistedcaldav.partitions import partitions
from twistedcaldav.util import (
    KeychainAccessError, KeychainPasswordNotFound, getPasswordFromKeychain, )

log = Logger()

DEFAULT_CONFIG_FILE = "/etc/caldavd/caldavd.plist"

DEFAULT_SERVICE_PARAMS = {
    "twistedcaldav.directory.xmlfile.XMLDirectoryService": {
        "xmlFile": "/etc/caldavd/accounts.xml",
    },
    "twistedcaldav.directory.appleopendirectory.OpenDirectoryService": {
        "node": "/Search",
        "cacheTimeout": 30,
    },
}

DEFAULT_AUGMENT_PARAMS = {
    "twistedcaldav.directory.augment.AugmentXMLDB": {
        "xmlFiles": ["/etc/caldavd/augments.xml",],
    },
    "twistedcaldav.directory.augment.AugmentSqliteDB": {
        "dbpath": "/etc/caldavd/augments.sqlite",
    },
    "twistedcaldav.directory.augment.AugmentPostgreSQLDB": {
        "host": "localhost",
        "database": "augments",
    },
}

DEFAULT_PROXYDB_PARAMS = {
    "twistedcaldav.directory.calendaruserproxy.ProxySqliteDB": {
        "dbpath": "/etc/caldavd/proxies.sqlite",
    },
    "twistedcaldav.directory.calendaruserproxy.ProxyPostgreSQLDB": {
        "host": "localhost",
        "database": "proxies",
    },
}

DEFAULT_CONFIG = {
    # Note: Don't use None values below; that confuses the command-line parser.

    #
    # Public network address information
    #
    #    This is the server's public network address, which is provided to
    #    clients in URLs and the like.  It may or may not be the network
    #    address that the server is listening to directly, though it is by
    #    default.  For example, it may be the address of a load balancer or
    #    proxy which forwards connections to the server.
    #
    "ServerHostName": "", # Network host name.
    "HTTPPort": 0,        # HTTP port (0 to disable HTTP)
    "SSLPort" : 0,        # SSL port (0 to disable HTTPS)
    "RedirectHTTPToHTTPS" : False, # If True, all nonSSL requests redirected to an SSL Port
    "SSLMethod" : "SSLv3_METHOD", # SSLv2_METHOD, SSLv3_METHOD, SSLv23_METHOD, TLSv1_METHOD

    #
    # Network address configuration information
    #
    #    This configures the actual network address that the server binds to.
    #
    "BindAddresses": [],   # List of IP addresses to bind to [empty = all]
    "BindHTTPPorts": [],   # List of port numbers to bind to for HTTP [empty = same as "Port"]
    "BindSSLPorts" : [],   # List of port numbers to bind to for SSL [empty = same as "SSLPort"]

    #
    # Data store
    #
    "DataRoot"                : "/Library/CalendarServer/Data",
    "DocumentRoot"            : "/Library/CalendarServer/Documents",
    "UserQuota"               : 104857600, # User quota (in bytes)
    "MaximumAttachmentSize"   :   1048576, # Attachment size limit (in bytes)
    "MaxAttendeesPerInstance" :       100, # Maximum number of unique attendees
    "MaxInstancesForRRULE"    :       400, # Maximum number of instances for an RRULE
    "WebCalendarRoot"         : "/usr/share/collaboration",

    "Aliases": {},

    #
    # Directory service
    #
    #    A directory service provides information about principals (eg.
    #    users, groups, locations and resources) to the server.
    #
    "DirectoryService": {
        "type": "twistedcaldav.directory.xmlfile.XMLDirectoryService",
        "params": DEFAULT_SERVICE_PARAMS["twistedcaldav.directory.xmlfile.XMLDirectoryService"],
    },

    #
    # Augment service
    #
    #    Augments for the directory service records to add calendar specific attributes.
    #
    "AugmentService": {
        "type": "twistedcaldav.directory.augment.AugmentXMLDB",
        "params": DEFAULT_AUGMENT_PARAMS["twistedcaldav.directory.augment.AugmentXMLDB"],
    },

    #
    # Proxies
    #
    "ProxyDBService": {
        "type": "twistedcaldav.directory.calendaruserproxy.ProxySqliteDB",
        "params": DEFAULT_PROXYDB_PARAMS["twistedcaldav.directory.calendaruserproxy.ProxySqliteDB"],
    },
    "ProxyLoadFromFile": "",    # Allows for initialization of the proxy database from an XML file

    #
    # Special principals
    #
    "AdminPrincipals": [],                       # Principals with "DAV:all" access (relative URLs)
    "ReadPrincipals": [],                        # Principals with "DAV:read" access (relative URLs)
    "SudoersFile": "/etc/caldavd/sudoers.plist", # Principals that can pose as other principals
    "EnableProxyPrincipals": True,               # Create "proxy access" principals

    #
    # Permissions
    #
    "EnableAnonymousReadRoot": True,    # Allow unauthenticated read access to /
    "EnableAnonymousReadNav": False,    # Allow unauthenticated read access to hierachcy
    "EnablePrincipalListings": True,    # Allow listing of principal collections
    "EnableMonolithicCalendars": True,  # Render calendar collections as a monolithic iCalendar object

    #
    # Client controls
    #
    "RejectClients": [], # List of regexes for clients to disallow

    #
    # Authentication
    #
    "Authentication": {
        "Basic": { "Enabled": False },     # Clear text; best avoided
        "Digest": {                        # Digest challenge/response
            "Enabled": True,
            "Algorithm": "md5",
            "Qop": "",
        },
        "Kerberos": {                       # Kerberos/SPNEGO
            "Enabled": False,
            "ServicePrincipal": ""
        },
        "Wiki": {
            "Enabled": False,
            "Cookie": "sessionID",
            "URL": "http://127.0.0.1:8086/RPC2",
            "UserMethod": "userForSession",
            "WikiMethod": "accessLevelForUserWikiCalendar",
        },
    },

    #
    # Logging
    #
    "AccessLogFile"  : "/var/log/caldavd/access.log",  # Apache-style access log
    "ErrorLogFile"   : "/var/log/caldavd/error.log",   # Server activity log
    "ServerStatsFile": "/var/run/caldavd/stats.plist",
    "PIDFile"        : "/var/run/caldavd.pid",
    "RotateAccessLog"   : False,
    "EnableExtendedAccessLog": True,
    "DefaultLogLevel"   : "",
    "LogLevels"         : {},

    "AccountingCategories": {
        "iTIP": False,
    },
    "AccountingPrincipals": [],
    "AccountingLogRoot"   : "/var/log/caldavd/accounting",

    "GlobalStatsSocket"           : "/var/run/caldavd-stats.sock", 
    "GlobalStatsLoggingPeriod"    : 60, 
    "GlobalStatsLoggingFrequency" : 12, 

    #
    # SSL/TLS
    #
    "SSLCertificate"     : "",  # Public key
    "SSLPrivateKey"      : "",  # Private key
    "SSLAuthorityChain"  : "",  # Certificate Authority Chain
    "SSLPassPhraseDialog": "/etc/apache2/getsslpassphrase",
    "SSLCertAdmin"       : "/usr/sbin/certadmin",

    #
    # Process management
    #

    # Username and Groupname to drop privileges to, if empty privileges will
    # not be dropped.

    "UserName": "",
    "GroupName": "",
    "ProcessType": "Combined",
    "MultiProcess": {
        "ProcessCount": 0,
        "MinProcessCount": 4,
        "LoadBalancer": {
            "Enabled": True,
            "Scheduler": "LeastConnections",
        },
        "StaggeredStartup": {
            "Enabled": False,
            "Interval": 15,
        },
    },

    #
    # Service ACLs
    #
    "EnableSACLs": False,

    #
    # Non-standard CalDAV extensions
    #
    "EnableDropBox"           : False, # Calendar Drop Box
    "EnablePrivateEvents"     : False, # Private Events
    "EnableTimezoneService"   : False, # Timezone service

    #
    # Web-based administration
    #
    "EnableWebAdmin"          : True,

    #
    # Scheduling related options
    #

    "Scheduling": {
        
        "CalDAV": {
            "EmailDomain"                : "",    # Domain for mailto calendar user addresses on this server
            "HTTPDomain"                 : "",    # Domain for http calendar user addresses on this server
            "AddressPatterns"            : [],    # Reg-ex patterns to match local calendar user addresses
            "OldDraftCompatibility"      : True,  # Whether to maintain compatibility with non-implicit mode
            "ScheduleTagCompatibility"   : True,  # Whether to support older clients that do not use Schedule-Tag feature
            "EnablePrivateComments"      : True,  # Private comments from attendees to organizer
        },

        "iSchedule": {
            "Enabled"          : False, # iSchedule protocol
            "AddressPatterns"  : [],    # Reg-ex patterns to match iSchedule-able calendar user addresses
            "Servers"          : "/etc/caldavd/servertoserver.xml",    # iSchedule server configurations
        },

        "iMIP": {
            "Enabled"          : False, # Server-to-iMIP protocol
            "MailGatewayServer" : "localhost",
            "MailGatewayPort"   : 62310,
            "Username"          : "com.apple.calendarserver", # For account injecting replies
            "Password"          : "",    # For account injecting replies
            "Sending": {
                "Server"        : "",    # SMTP server to relay messages through
                "Port"          : 587,   # SMTP server port to relay messages through
                "Address"       : "",    # 'From' address for server
                "UseSSL"        : True,
                "Username"      : "",    # For account sending mail
                "Password"      : "",    # For account sending mail
            },
            "Receiving": {
                "Server"        : "",    # Server to retrieve email messages from
                "Port"          : 0,     # Server port to retrieve email messages from
                "UseSSL"        : True,
                "Type"          : "",    # Type of message access server: 'pop' or 'imap'
                "PollingSeconds"    : 30,  # How often to fetch mail
                "Username"      : "",    # For account receving mail
                "Password"      : "",    # For account receving mail
            },
            "AddressPatterns"   : [],    # Reg-ex patterns to match iMIP-able calendar user addresses
            "MailTemplatesDirectory": "/usr/share/caldavd/share/email_templates", # Directory containing HTML templates for email invitations (invite.html, cancel.html)
            "MailIconsDirectory": "/usr/share/caldavd/share/date_icons", # Directory containing language-specific subdirectories containing date-specific icons for email invitations
            "InvitationDaysToLive" : 90, # How many days invitations are valid
        },

        "Options" : {
            "AllowGroupAsOrganizer"      : False, # Allow groups to be Organizers
            "AllowLocationAsOrganizer"   : False, # Allow locations to be Organizers
            "AllowResourceAsOrganizer"   : False, # Allow resources to be Organizers
        }
    },

    "FreeBusyURL": {
        "Enabled"          : False, # Per-user free-busy-url protocol
        "TimePeriod"       : 14,    # Number of days into the future to generate f-b data if no explicit time-range is specified
        "AnonymousAccess"  : False, # Allow anonymous read access to free-busy URL
    },

    #
    # Notifications
    #
    "Notifications" : {
        "Enabled": False,
        "CoalesceSeconds" : 3,
        "InternalNotificationHost" : "localhost",
        "InternalNotificationPort" : 62309,
        "BindAddress" : "127.0.0.1",

        "Services" : {
            "SimpleLineNotifier" : {
                "Service" : "twistedcaldav.notify.SimpleLineNotifierService",
                "Enabled" : False,
                "Port" : 62308,
            },
            "XMPPNotifier" : {
                "Service" : "twistedcaldav.notify.XMPPNotifierService",
                "Enabled" : False,
                "Host" : "", # "xmpp.host.name"
                "Port" : 5222,
                "JID" : "", # "jid@xmpp.host.name/resource"
                "Password" : "",
                "ServiceAddress" : "", # "pubsub.xmpp.host.name"
                "NodeConfiguration" : {
                    "pubsub#deliver_payloads" : "1",
                    "pubsub#persist_items" : "1",
                },
                "KeepAliveSeconds" : 120,
                "HeartbeatMinutes" : 30,
                "AllowedJIDs": [],
            },
        }
    },

    #
    # Partitioning
    #
    "EnablePartitions":    False,   # Partitioning enabled or not
    "ServerPartitionID":   "",      # Unique ID for this server's partition instance.
    "PartitionConfigFile": "/etc/caldavd/partitions.plist", # File path for partition information

    #
    # Performance tuning
    #

    # Set the maximum number of outstanding requests to this server.
    "MaxRequests": 600,

    "ListenBacklog": 50,
    "IdleConnectionTimeOut": 15,
    "UIDReservationTimeOut": 30 * 60,


    #
    # Localization
    #
    "Localization" : {
        "TranslationsDirectory" : "/usr/share/caldavd/share/translations",
        "LocalesDirectory" : "/usr/share/caldavd/share/locales",
        "Language" : "English",
    },


    #
    # Implementation details
    #
    #    The following are specific to how the server is built, and useful
    #    for development, but shouldn't be needed by users.
    #

    # Twisted
    "Twisted": {
        "twistd": "/usr/share/caldavd/bin/twistd",
        "reactor": "select",
    },

    # Python Director
    "PythonDirector": {
        "pydir": "/usr/share/caldavd/bin/pydir.py",
        "ConfigFile": "/etc/caldavd/pydir.xml",
        "ControlSocket": "/var/run/caldavd-pydir.sock",
    },

    # Umask
    "umask": 0027,

    # A TCP port used for communication between the child and master
    # processes (bound to 127.0.0.1). Specify 0 to let OS assign a port.
    "ControlPort": 0,

    # A unix socket used for communication between the child and master
    # processes. If blank, then an AF_INET socket is used instead.
    "ControlSocket": "/var/run/caldavd.sock",


    # Support for Content-Encoding compression options as specified in
    # RFC2616 Section 3.5
    "ResponseCompression": True,

    # The retry-after value (in seconds) to return with a 503 error
    "HTTPRetryAfter": 180,

    # Profiling options
    "Profiling": {
        "Enabled": False,
        "BaseDirectory": "/tmp/stats",
    },

    "Memcached": {
        "MaxClients": 5,
        "ClientEnabled": True,
        "ServerEnabled": True,
        "BindAddress": "127.0.0.1",
        "Port": 11211,
        "memcached": "memcached", # Find in PATH
        "MaxMemory": 0, # Megabytes
        "Options": [],
    },

    "EnableKeepAlive": True,
    "ResponseCacheTimeout": 30, # Minutes
}

class PListConfigProvider(ConfigProvider):
    
    def loadConfig(self):
        configDict = {}
        if self._configFileName:
            try:
                configDict = readPlist(self._configFileName)
            except (IOError, OSError):                                    
                log.error("Configuration file does not exist or is inaccessible: %s" % (self._configFileName,))
            else:
                configDict = _cleanup(configDict, self._defaults)
        return configDict


def _updateHostName(configDict):
    if not configDict.ServerHostName:
        from socket import getfqdn
        hostname = getfqdn()
        if not hostname:
            hostname = "localhost"
        configDict.ServerHostName = hostname

def _preUpdateDirectoryService(configDict, items):
    # Special handling for directory services configs
    dsType = items.get("DirectoryService", {}).get("type", None)
    if dsType is None:
        dsType = configDict.DirectoryService.type
    else:
        if dsType == configDict.DirectoryService.type:
            oldParams = configDict.DirectoryService.params
            newParams = items.DirectoryService.get("params", {})
            _mergeData(oldParams, newParams)
        else:
            if dsType in DEFAULT_SERVICE_PARAMS:
                configDict.DirectoryService.params = copy.deepcopy(DEFAULT_SERVICE_PARAMS[dsType])
            else:
                configDict.DirectoryService.params = {}

    for param in items.get("DirectoryService", {}).get("params", {}):
        if dsType in DEFAULT_SERVICE_PARAMS and param not in DEFAULT_SERVICE_PARAMS[dsType]:
            log.warn("Parameter %s is not supported by service %s" % (param, dsType))
            
def _postUpdateDirectoryService(configDict):
    if configDict.DirectoryService.type in DEFAULT_SERVICE_PARAMS:
        for param in tuple(configDict.DirectoryService.params):
            if param not in DEFAULT_SERVICE_PARAMS[configDict.DirectoryService.type]:
                del configDict.DirectoryService.params[param]

def _postUpdateAugmentService(configDict):
    if configDict.AugmentService.type in DEFAULT_AUGMENT_PARAMS:
        for param in tuple(configDict.AugmentService.params):
            if param not in DEFAULT_AUGMENT_PARAMS[configDict.AugmentService.type]:
                log.warn("Parameter %s is not supported by service %s" % (param, configDict.AugmentService.type))
                del configDict.AugmentService.params[param]

def _postUpdateProxyDBService(configDict):
    if configDict.ProxyDBService.type in DEFAULT_PROXYDB_PARAMS:
        for param in tuple(configDict.ProxyDBService.params):
            if param not in DEFAULT_PROXYDB_PARAMS[configDict.ProxyDBService.type]:
                log.warn("Parameter %s is not supported by service %s" % (param, configDict.ProxyDBService.type))
                del configDict.ProxyDBService.params[param]

def _updateACLs(configDict):
    #
    # Base resource ACLs
    #
    def readOnlyACE(allowAnonymous):
        if allowAnonymous:
            reader = davxml.All()
        else:
            reader = davxml.Authenticated()

        return davxml.ACE(
            davxml.Principal(reader),
            davxml.Grant(
                davxml.Privilege(davxml.Read()),
                davxml.Privilege(davxml.ReadCurrentUserPrivilegeSet()),
            ),
            davxml.Protected(),
        )

    configDict.AdminACEs = tuple(
        davxml.ACE(
            davxml.Principal(davxml.HRef(principal)),
            davxml.Grant(davxml.Privilege(davxml.All())),
            davxml.Protected(),
            TwistedACLInheritable(),
        )
        for principal in configDict.AdminPrincipals
    )

    configDict.ReadACEs = tuple(
        davxml.ACE(
            davxml.Principal(davxml.HRef(principal)),
            davxml.Grant(
                davxml.Privilege(davxml.Read()),
                davxml.Privilege(davxml.ReadCurrentUserPrivilegeSet()),
            ),
            davxml.Protected(),
            TwistedACLInheritable(),
        )
        for principal in configDict.ReadPrincipals
    )

    configDict.RootResourceACL = davxml.ACL(
        # Read-only for anon or authenticated, depending on config
        readOnlyACE(configDict.EnableAnonymousReadRoot),

        # Add inheritable all access for admins
        *configDict.AdminACEs
    )

    log.debug("Root ACL: %s" % (configDict.RootResourceACL.toxml(),))

    configDict.ProvisioningResourceACL = davxml.ACL(
        # Read-only for anon or authenticated, depending on config
        readOnlyACE(configDict.EnableAnonymousReadNav),

        # Add read and read-acl access for admins
        *[
            davxml.ACE(
                davxml.Principal(davxml.HRef(principal)),
                davxml.Grant(
                    davxml.Privilege(davxml.Read()),
                    davxml.Privilege(davxml.ReadACL()),
                    davxml.Privilege(davxml.ReadCurrentUserPrivilegeSet()),
                ),
                davxml.Protected(),
            )
            for principal in configDict.AdminPrincipals
        ]
    )

    log.debug("Nav ACL: %s" % (configDict.ProvisioningResourceACL.toxml(),))

def _updateRejectClients(configDict):
    #
    # Compile RejectClients expressions for speed
    #
    try:
        configDict.RejectClients = [re.compile(x) for x in configDict.RejectClients if x]
    except re.error, e:
        raise ConfigurationError("Invalid regular expression in RejectClients: %s" % (e,))

def _updateDropBox(configDict):
    #
    # FIXME: Use the config object instead of doing this here
    #
    from twistedcaldav.resource import CalendarPrincipalResource
    CalendarPrincipalResource.enableDropBox(configDict.EnableDropBox)

def _updateLogLevels(configDict):
    clearLogLevels()

    try:
        if "DefaultLogLevel" in configDict:
            level = configDict["DefaultLogLevel"]
            if level:
                setLogLevelForNamespace(None, level)

        if "LogLevels" in configDict:
            for namespace in configDict["LogLevels"]:
                setLogLevelForNamespace(namespace, configDict["LogLevels"][namespace])

    except InvalidLogLevelError, e:
        raise ConfigurationError("Invalid log level: %s" % (e.level))

def _updateNotifications(configDict):
    #
    # Notifications
    #

    # Reloading not supported -- requires process running as root
    if getattr(configDict, "_reloading", False):
        return

    for key, service in configDict.Notifications["Services"].iteritems():
        if service["Enabled"]:
            configDict.Notifications["Enabled"] = True
            break
    else:
        configDict.Notifications["Enabled"] = False

    for key, service in configDict.Notifications["Services"].iteritems():
        if (
            service["Service"] == "twistedcaldav.notify.XMPPNotifierService" and
            service["Enabled"]
        ):
            # Get password from keychain.  If not there, fall back to what
            # is in the plist.
            try:
                password = getPasswordFromKeychain(service["JID"])
                service["Password"] = password
                log.info("XMPP password successfully retreived from keychain")
            except KeychainAccessError:
                # The system doesn't support keychain
                pass
            except KeychainPasswordNotFound:
                # The password doesn't exist in the keychain.
                log.error("XMPP password not found in keychain")

            # Check for empty fields
            for key, value in service.iteritems():
                if not value and key not in ("AllowedJIDs", "HeartbeatMinutes", "Password"):
                    raise ConfigurationError("Invalid %s for XMPPNotifierService: %r"
                                             % (key, value))

def _updateScheduling(configDict):
    #
    # Scheduling
    #

    # Reloading not supported -- requires process running as root
    if getattr(configDict, "_reloading", False):
        return

    service = configDict.Scheduling["iMIP"]

    if service["Enabled"]:

        # Get password for the user that is allowed to inject iMIP replies
        # to the server's /inbox; if not available, fall back to plist
        if service["Username"]:
            try:
                service["Password"] = getPasswordFromKeychain(service["Username"])
            except KeychainAccessError:
                # The system doesn't support keychain
                pass
            except KeychainPasswordNotFound:
                # The password doesn't exist in the keychain.
                log.info("iMIP injecting password not found in keychain")

        for direction in ("Sending", "Receiving"):
            if service[direction].Username:
                # Get password from keychain.  If not there, fall back to
                # what is in the plist.
                try:
                    account = "%s@%s" % (
                        service[direction].Username,
                        service[direction].Server
                    )
                    password = getPasswordFromKeychain(account)
                    service[direction]["Password"] = password
                    log.info("iMIP %s password successfully retreived from keychain" % (direction,))
                except KeychainAccessError:
                    # The system doesn't support keychain
                    pass
                except KeychainPasswordNotFound:
                    # The password doesn't exist in the keychain.
                    log.info("iMIP %s password not found in keychain" %
                        (direction,))

def _updatePartitions(configDict):
    #
    # Partitions
    #

    if configDict.EnablePartitions:
        partitions.setSelfPartition(configDict.ServerPartitionID)
        partitions.readConfig(configDict.PartitionConfigFile)
    else:
        partitions.clear()

PRE_UPDATE_HOOKS = (
    _preUpdateDirectoryService,
    )
POST_UPDATE_HOOKS = (
    _updateHostName,
    _postUpdateDirectoryService,
    _postUpdateAugmentService,
    _postUpdateProxyDBService,
    _updateACLs,
    _updateRejectClients,
    _updateDropBox,
    _updateLogLevels,
    _updateNotifications,
    _updateScheduling,
    _updatePartitions,
    )
    
def _cleanup(configDict, defaultDict):
    cleanDict = copy.deepcopy(configDict)

    def unknown(key):
        config_key = "ICAL_SERVER_CONFIG_VALIDATION"
        config_key_value = "loose"
        if config_key in os.environ and os.environ[config_key] == config_key_value:
            pass
        else:
            log.err("Ignoring unknown configuration option: %r - you can optionally bypass this validation by setting a sys env var %s to '%s'" % (key, config_key, config_key_value))
            del cleanDict[key]

    def deprecated(oldKey, newKey):
        log.err("Configuration option %r is deprecated in favor of %r." % (oldKey, newKey))
        if oldKey in configDict and newKey in configDict:
            raise ConfigurationError(
                "Both %r and %r options are specified; use the %r option only."
                % (oldKey, newKey, newKey)
            )

    def renamed(oldKey, newKey):
        deprecated(oldKey, newKey)
        cleanDict[newKey] = configDict[oldKey]
        del cleanDict[oldKey]

    renamedOptions = {
#       "BindAddress": "BindAddresses",
    }

    for key in configDict:
        if key in defaultDict:
            continue

        elif key in renamedOptions:
            renamed(key, renamedOptions[key])

#       elif key == "pydirConfig":
#           deprecated(key, "PythonDirector -> pydir")
#           if "PythonDirector" not in cleanDict:
#               cleanDict["PythonDirector"] = {}
#           cleanDict["PythonDirector"]["ConfigFile"] = cleanDict["pydirConfig"]
#           del cleanDict["pydirConfig"]

        else:
            unknown(key,)

    return cleanDict

config.setProvider(PListConfigProvider(DEFAULT_CONFIG))
config.addPreUpdateHook(PRE_UPDATE_HOOKS)
config.addPostUpdateHook(POST_UPDATE_HOOKS)
