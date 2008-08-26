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
##

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, returnValue

from twisted.python.failure import Failure

from twisted.web2 import responsecode
from twisted.web2.dav import davxml
from twisted.web2.dav.http import ErrorResponse
from twisted.web2.dav.resource import AccessDeniedError
from twisted.web2.dav.util import joinURL
from twisted.web2.http import HTTPError

from twistedcaldav import caldavxml
from twistedcaldav.caldavxml import caldav_namespace
from twistedcaldav.config import config
from twistedcaldav.customxml import calendarserver_namespace
from twistedcaldav.itip import iTipProcessor
from twistedcaldav.log import Logger
from twistedcaldav.method import report_common
from twistedcaldav.resource import isCalendarCollectionResource
from twistedcaldav.scheduling.cuaddress import LocalCalendarUser,\
    RemoteCalendarUser
from twistedcaldav.scheduling.delivery import DeliveryService
from twistedcaldav.scheduling.processing import ImplicitProcessor,\
    ImplicitProcessorException

import md5
import time

"""
Class that handles delivery of scheduling messages via CalDAV.
"""

__all__ = [
    "ScheduleViaCalDAV",
]

log = Logger()

class ScheduleViaCalDAV(DeliveryService):
    
    def __init__(self, scheduler, recipients, responses, freebusy):

        self.scheduler = scheduler
        self.recipients = recipients
        self.responses = responses
        self.freebusy = freebusy

    @classmethod
    def serviceType(cls):
        return DeliveryService.serviceType_caldav

    @classmethod
    def matchCalendarUserAddress(cls, cuaddr):

        # Check for local address matches first
        if cuaddr.startswith("mailto:") and config.Scheduling[cls.serviceType()]["EmailDomain"]:
            splits = cuaddr[7:].split("?")
            domain = config.Scheduling[cls.serviceType()]["EmailDomain"]
            if splits[0].endswith(domain):
                return True

        elif (cuaddr.startswith("http://") or cuaddr.startswith("https://")) and config.Scheduling[cls.serviceType()]["HTTPDomain"]:
            splits = cuaddr.split(":")[0][2:].split("?")
            domain = config.Scheduling[cls.serviceType()]["HTTPDomain"]
            if splits[0].endswith(domain):
                return True

        elif cuaddr.startswith("/"):
            # Assume relative HTTP URL - i.e. on this server
            return True
        
        # Do default match
        return super(ScheduleViaCalDAV, cls).matchCalendarUserAddress(cuaddr)

    @inlineCallbacks
    def generateSchedulingResponses(self):
        
        # Extract the ORGANIZER property and UID value from the calendar data for use later
        organizerProp = self.scheduler.calendar.getOrganizerProperty()
        uid = self.scheduler.calendar.resourceUID()

        autoresponses = []
        for recipient in self.recipients:

            #
            # Check access controls
            #
            if isinstance(self.scheduler.organizer, LocalCalendarUser):
                try:
                    yield recipient.inbox.checkPrivileges(self.scheduler.request, (caldavxml.Schedule(),), principal=davxml.Principal(davxml.HRef(self.scheduler.organizer.principal.principalURL())))
                except AccessDeniedError:
                    log.err("Could not access Inbox for recipient: %s" % (recipient.cuaddr,))
                    err = HTTPError(ErrorResponse(responsecode.NOT_FOUND, (caldav_namespace, "recipient-permissions")))
                    self.responses.add(recipient.cuaddr, Failure(exc_value=err), reqstatus="3.8;No authority")
                
                    # Process next recipient
                    continue
            else:
                # TODO: need to figure out how best to do server-to-server authorization.
                # First thing would be to check for DAV:unauthenticated privilege.
                # Next would be to allow the calendar user address of the organizer/originator to be used
                # as a principal. 
                pass

            # Different behavior for free-busy vs regular invite
            if self.freebusy:
                yield self.generateFreeBusyResponse(recipient, self.responses, organizerProp, uid)
            else:
                yield self.generateResponse(recipient, self.responses, autoresponses)

        # Now we have to do auto-respond
        if len(autoresponses) != 0:
            # First check that we have a method that we can auto-respond to
            if not iTipProcessor.canAutoRespond(self.scheduler.calendar):
                autoresponses = []
            
        # Now do the actual auto response
        for principal, inbox, child in autoresponses:
            # Add delayed reactor task to handle iTIP responses
            itip = iTipProcessor()
            reactor.callLater(0.0, itip.handleRequest, *(self.scheduler.request, principal, inbox, self.scheduler.calendar.duplicate(), child))

    @inlineCallbacks
    def generateResponse(self, recipient, responses, autoresponses):
        # Hash the iCalendar data for use as the last path element of the URI path
        calendar_str = str(self.scheduler.calendar)
        name = md5.new(calendar_str + str(time.time()) + recipient.inbox.fp.path).hexdigest() + ".ics"
    
        # Get a resource for the new item
        childURL = joinURL(recipient.inboxURL, name)
        child = (yield self.scheduler.request.locateResource(childURL))

        # Do implicit scheduling message processing
        try:
            processor = ImplicitProcessor()
            processed, autoprocessed = (yield processor.doImplicitProcessing(
                self.scheduler.request,
                self.scheduler.calendar,
                self.scheduler.originator,
                recipient
            ))
        except ImplicitProcessorException, e:
            log.err("Could not store data in Inbox : %s" % (recipient.inbox,))
            err = HTTPError(ErrorResponse(responsecode.FORBIDDEN, (caldav_namespace, "recipient-permissions")))
            responses.add(recipient.cuaddr, Failure(exc_value=err), reqstatus=e.msg)
            returnValue(False)

        if autoprocessed:
            # No need to write the inbox item as it has already been auto-processed
            responses.add(recipient.cuaddr, responsecode.OK, reqstatus="2.0;Success")
            returnValue(True)
        else:
            # Copy calendar to inbox 
            try:
                from twistedcaldav.method.put_common import StoreCalendarObjectResource
                yield StoreCalendarObjectResource(
                             request=self.scheduler.request,
                             destination = child,
                             destination_uri = childURL,
                             destinationparent = recipient.inbox,
                             destinationcal = True,
                             calendar = self.scheduler.calendar,
                             isiTIP = True
                         ).run()
            except:
                # FIXME: Bare except
                log.err("Could not store data in Inbox : %s" % (recipient.inbox,))
                err = HTTPError(ErrorResponse(responsecode.FORBIDDEN, (caldav_namespace, "recipient-permissions")))
                responses.add(recipient.cuaddr, Failure(exc_value=err), reqstatus="3.8;No authority")
                returnValue(False)
            else:
                responses.add(recipient.cuaddr, responsecode.OK, reqstatus="2.0;Success")
    
                # Store CALDAV:originator property
                child.writeDeadProperty(caldavxml.Originator(davxml.HRef(self.scheduler.originator.cuaddr)))
            
                # Store CALDAV:recipient property
                child.writeDeadProperty(caldavxml.Recipient(davxml.HRef(recipient.cuaddr)))
            
                # Store CALDAV:schedule-state property
                child.writeDeadProperty(caldavxml.ScheduleState(caldavxml.ScheduleProcessed() if processed else caldavxml.ScheduleUnprocessed()))
            
                # Look for auto-schedule option
                if not processed and recipient.principal.autoSchedule():
                    autoresponses.append((recipient.principal, recipient.inbox, child))
                    
                returnValue(True)
    
    @inlineCallbacks
    def generateFreeBusyResponse(self, recipient, responses, organizerProp, uid):

        # Extract the ATTENDEE property matching current recipient from the calendar data
        cuas = recipient.principal.calendarUserAddresses()
        attendeeProp = self.scheduler.calendar.getAttendeeProperty(cuas)

        remote = isinstance(self.scheduler.organizer, RemoteCalendarUser)

        try:
            fbresult = (yield self.generateAttendeeFreeBusyResponse(
                recipient,
                organizerProp,
                uid,
                attendeeProp,
                remote,
            ))
        except:
            log.err("Could not determine free busy information: %s" % (recipient.cuaddr,))
            err = HTTPError(ErrorResponse(responsecode.FORBIDDEN, (caldav_namespace, "recipient-permissions")))
            responses.add(recipient.cuaddr, Failure(exc_value=err), reqstatus="3.8;No authority")
            returnValue(False)
        else:
            responses.add(recipient.cuaddr, responsecode.OK, reqstatus="2.0;Success", calendar=fbresult)
            returnValue(True)
    
    @inlineCallbacks
    def generateAttendeeFreeBusyResponse(self, recipient, organizerProp, uid, attendeeProp, remote):

        # Find the current recipients calendar-free-busy-set
        fbset = (yield recipient.principal.calendarFreeBusyURIs(self.scheduler.request))

        # First list is BUSY, second BUSY-TENTATIVE, third BUSY-UNAVAILABLE
        fbinfo = ([], [], [])
    
        # Process the availability property from the Inbox.
        has_prop = (yield recipient.inbox.hasProperty((calendarserver_namespace, "calendar-availability"), self.scheduler.request))
        if has_prop:
            availability = (yield recipient.inbox.readProperty((calendarserver_namespace, "calendar-availability"), self.scheduler.request))
            availability = availability.calendar()
            report_common.processAvailabilityFreeBusy(availability, fbinfo, self.scheduler.timeRange)

        # Check to see if the recipient is the same calendar user as the organizer.
        # Needed for masked UID stuff.
        if isinstance(self.scheduler.organizer, LocalCalendarUser):
            same_calendar_user = self.scheduler.organizer.principal.principalURL() == recipient.principal.principalURL()
        else:
            same_calendar_user = False

        # Now process free-busy set calendars
        matchtotal = 0
        for calendarResourceURL in fbset:
            calendarResource = (yield self.scheduler.request.locateResource(calendarResourceURL))
            if calendarResource is None or not calendarResource.exists() or not isCalendarCollectionResource(calendarResource):
                # We will ignore missing calendars. If the recipient has failed to
                # properly manage the free busy set that should not prevent us from working.
                continue
         
            matchtotal = (yield report_common.generateFreeBusyInfo(
                self.scheduler.request,
                calendarResource,
                fbinfo,
                self.scheduler.timeRange,
                matchtotal,
                excludeuid = self.scheduler.excludeUID,
                organizer = self.scheduler.organizer.cuaddr,
                same_calendar_user = same_calendar_user,
                servertoserver=remote
            ))
    
        # Build VFREEBUSY iTIP reply for this recipient
        fbresult = report_common.buildFreeBusyResult(
            fbinfo,
            self.scheduler.timeRange,
            organizer = organizerProp,
            attendee = attendeeProp,
            uid = uid,
            method = "REPLY"
        )

        returnValue(fbresult)
