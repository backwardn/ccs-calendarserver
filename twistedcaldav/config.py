##
# Copyright (c) 2005-2007 Apple Inc. All rights reserved.
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
#
# DRI: David Reid, dreid@apple.com
##

import os

from twistedcaldav.py.plistlib import readPlist

defaultConfigFile = "/etc/caldavd/caldavd.plist"

defaultConfig = {
    #
    # Public network address information
    #
    #    This is the server's public network address, which is provided to
    #    clients in URLs and the like.  It may or may not be the network
    #    address that the server is listening to directly, though it is by
    #    default.  For example, it may be the address of a load balancer or
    #    proxy which forwards connections to the server.
    #
    "ServerHostName": "localhost", # Network host name.
    "HTTPPort": None,              # HTTP port (None to disable HTTP)
    "SSLPort" : None,              # SSL port (None to disable HTTPS)

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
    "DocumentRoot": "/Library/CalendarServer/Documents",
    "UserQuota"            : 104857600, # User quota (in bytes)
    "MaximumAttachmentSize":   1048576, # Attachment size limit (in bytes)

    #
    # Directory service
    #
    #    A directory service provides information about principals (eg.
    #    users, groups, locations and resources) to the server.
    #
    "DirectoryService": {
        "type": "twistedcaldav.directory.appleopendirectory.OpenDirectoryService",
        "params": {
            "node": "/Search",
            "requireComputerRecord": True,
        },
    },

    #
    # Special principals
    #
    "AdminPrincipals": [],                       # Principals with "DAV:all" access (relative URLs)
    "SudoersFile": "/etc/caldavd/sudoers.plist", # Principals that can pose as other principals
    "EnableProxyPrincipals": True,               # Create "proxy access" principals

    #
    # Authentication
    #
    "Authentication": {
        "Basic"   : { "Enabled": False },                     # Clear text; best avoided
        "Digest"  : { "Enabled": True,  "Algorithm": "md5" }, # Digest challenge/response
        "Kerberos": { "Enabled": False, "Realm": "" },        # Kerberos/SPNEGO
    },

    #
    # Logging
    #
    "Verbose": False,
    "AccessLogFile"  : "/var/log/caldavd/access.log",                   # Apache-style access log
    "ErrorLogFile"   : "/var/log/caldavd/error.log",                    # Server activity log
    "ServerStatsFile": "/Library/CalendarServer/Documents/stats.plist",
    "PIDFile"        : "/var/run/caldavd.pid",

    #
    # SSL/TLS
    #
    "SSLCertificate": "/etc/certificates/Default.crt", # Public key
    "SSLPrivateKey": "/etc/certificates/Default.key",  # Private key

    #
    # Process management
    #
    "UserName": "daemon",
    "GroupName": "daemon",
    "ProcessType": "Slave",
    "MultiProcess": {
        "ProcessCount": 4,
        "LoadBalancer": {
            "Enabled": True,
            "Scheduler": "LeastConnections",
        },
    },

    #
    # Service ACLs
    #
    "EnableSACLs": False,

    #
    # Non-standard CalDAV extensions
    #
    "EnableDropBox"      : False, # Calendar Drop Box
    "EnableNotifications": False, # Drop Box Notifications

    #
    # Implementation details
    #
    #    The following are specific to how the server is built, and useful
    #    for development, but shouldn't be needed by users.
    #

    # Twisted
    "Twisted": {
        "twistd": "/usr/share/caldavd/bin/twistd",
    },

    # Python Director
    "PythonDirector": {
        "pydir": "/usr/share/caldavd/bin/pydir++.py",
        "ConfigFile": "/etc/caldavd/pydir.xml",
    },
}

class Config (object):
    def __init__(self, defaults):
        self.update(defaults)

    def update(self, items):
        items = items.iteritems()
        for key, value in items:
            setattr(self, key, value)

class ConfigurationError (RuntimeError):
    """
    Invalid server configuration.
    """

config = Config(defaultConfig)

def parseConfig(configFile):
    if os.path.exists(configFile):
        plist = readPlist(configFile)
        config.update(plist)
