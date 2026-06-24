# Tour Tracker

Tour Tracker tracks artist tour activity and separates events that should notify the user from events that need human judgment.

## Language

**Confirmed Local Event**:
An event that is trusted enough to notify about because it confidently matches one of the user's tracked location profiles and comes from a reliable source.
_Avoid_: Coming event, match, hit

**Event Source**:
A place the app checks for tour activity for a tracked artist.
_Avoid_: Source URL, feed, provider

**Local Run**:
A sequence of upcoming confirmed local events for the same tracked artist.
_Avoid_: Tour leg, current dates, coming window

**Location Alias**:
An alternate place name that should be treated as part of a tracked location when deciding whether an event matters.
_Avoid_: Suburb, nearby city, venue alias

**Paused Tracked Artist**:
A tracked artist that the user has temporarily excluded from routine checking.
_Avoid_: Disabled artist, inactive artist, ignored artist

**Review Candidate**:
An event that may be relevant but needs human judgment before it is trusted enough to notify about.
_Avoid_: Possible event, pending event, maybe

**Scan Run**:
One pass where the app checks tracked artists and their event sources for tour activity.
_Avoid_: Job, crawl, check

**Source Check**:
The result of checking one event source during a scan run.
_Avoid_: Fetch result, source result, crawl result

**Tracked Location**:
A place the user cares about when deciding whether an artist's event matters.
_Avoid_: Location profile, city, market

**Tracked Artist**:
A performer or group whose tour activity the user wants the app to monitor.
_Avoid_: Artist, comedian, act

**Unhealthy Event Source**:
An event source whose recent source checks suggest it may be missing, blocking, hiding, or failing to provide usable tour activity.
_Avoid_: Broken source, bad URL, failing source
