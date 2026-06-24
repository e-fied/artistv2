# Tour Tracker

Tour Tracker tracks artist tour activity and separates events that should notify the user from events that need human judgment.

## Language

**Confirmed Local Event**:
An event that is trusted enough to notify about because it confidently matches one of the user's tracked location profiles and comes from a reliable source.
_Avoid_: Coming event, match, hit

**Review Candidate**:
An event that may be relevant but needs human judgment before it is trusted enough to notify about.
_Avoid_: Possible event, pending event, maybe

**Tracked Location**:
A place the user cares about when deciding whether an artist's event matters.
_Avoid_: Location profile, city, market

**Event Source**:
A place the app checks for tour activity for a tracked artist.
_Avoid_: Source URL, feed, provider
