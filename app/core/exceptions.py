class AppError(Exception):
    """Base class for the errors this application raises on purpose.

    Every one of these carries two messages. `detail` is what the client is
    told; the exception's own `str()` is for logs and may carry context that
    must not leave the process, such as which address was already taken.

    Nothing here mentions HTTP. Turning these into status codes is the API
    layer's job, in `app/api/errors.py`, which is the whole point of the
    split: a service can raise the right error without knowing that a 409
    exists.
    """

    detail = "Something went wrong"

    def __init__(self, message: str = "", *, detail: str | None = None) -> None:
        # An instance may override the class-wide public message when the
        # same error means something more specific to the caller.
        if detail is not None:
            self.detail = detail

        super().__init__(message or self.detail)

    def headers(self) -> dict[str, str] | None:
        """Response headers this particular failure needs, if any.

        Almost none do -- the ones that are the same for every instance
        of an error are declared next to its status code in
        `app/api/errors.py`. This is for a header whose value depends on
        the instance, which so far means Retry-After.
        """
        return None


class UserNotFoundError(AppError):
    """No user exists with the requested id."""

    detail = "User not found"

    def __init__(self, user_id: int) -> None:
        super().__init__(f"User not found: {user_id}")
        self.user_id = user_id


class EmailAlreadyExistsError(AppError):
    """The email address is already registered to someone."""

    detail = "Email already registered"

    def __init__(self, email: str) -> None:
        # The address belongs in the log line, not in the response.
        super().__init__(f"Email already registered: {email}")
        self.email = email


class InvalidCredentialsError(AppError):
    """Authentication failed.

    Covers a wrong password, an unknown address and a token that does not
    hold up, on purpose: separating those would tell an attacker which
    accounts exist.
    """

    detail = "Incorrect email or password"


class InactiveUserError(AppError):
    """The credentials were right, but the account is deactivated."""

    detail = "Inactive user"

    def __init__(self, user_id: int) -> None:
        super().__init__(f"User is not active: {user_id}")
        self.user_id = user_id


class IncorrectPasswordError(AppError):
    """A password change was attempted without the current password.

    Separate from InvalidCredentialsError on purpose. The bearer token is
    valid and the caller is who they claim to be, so a 401 would tell the
    client its session had expired and send a perfectly good one back to
    the login screen. What failed is one field of the request.
    """

    detail = "Current password is incorrect"

    def __init__(self, user_id: int) -> None:
        super().__init__(f"Incorrect current password for user: {user_id}")
        self.user_id = user_id


class RateLimitExceededError(AppError):
    """Too many requests, too quickly, from whoever this was keyed on.

    Carries how long to wait, because a 429 without Retry-After tells a
    client to guess, and what clients guess is "immediately".
    """

    detail = "Too many requests. Try again shortly"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")
        self.retry_after = retry_after

    def headers(self) -> dict[str, str] | None:
        return {"Retry-After": str(self.retry_after)}


class InvalidVerificationTokenError(AppError):
    """The link will not do anything.

    Unknown, already used, expired, or issued for an address the account
    no longer has -- one answer for all four, and it says "or expired"
    without saying which. Whoever is holding it has proved nothing yet,
    and separating the cases would turn the endpoint into a way of asking
    whether a given link was ever real.

    Deliberately unlike InvitationExpiredError, which does distinguish
    expiry. An invitation arrives from a colleague and "ask them for
    another" is different advice from "check the address"; here the only
    advice either way is to request a fresh link, so there is nothing to
    buy with the distinction.
    """

    detail = "This link is invalid or has expired"


class EmailDeliveryError(AppError):
    """The message could not be handed to the mail server.

    Raised only where it is caught. Every send in this application runs
    after its response has gone, so nobody is waiting to be told -- what
    this is for is a log line that says delivery failed rather than one
    that says an unhandled exception happened in a request that worked.
    """

    detail = "The email could not be sent right now"


class InvalidRefreshTokenError(AppError):
    """The presented refresh token will not do anything.

    Unknown, already spent, or belonging to a session that has been
    revoked or has gone idle for too long -- all the same answer, for the
    reason InvalidCredentialsError collapses its cases: whoever is
    holding it has proved nothing, and telling them which of the four it
    was would tell them what to try next.
    """

    detail = "Invalid or expired refresh token"


class RefreshTokenReusedError(InvalidRefreshTokenError):
    """A refresh token came back after it had already been exchanged.

    The session has been revoked by the time this is raised. Told apart
    from an ordinary refusal on purpose, and this one leaks nothing: the
    holder had a real token, and the mechanism is public. What it buys is
    that the person who was signed out gets to know it was not a glitch.
    """

    detail = "That session was ended: a refresh token was used twice. Sign in again"


class SessionNotFoundError(AppError):
    """No live session with that id belongs to this account.

    Safe to distinguish from every other refusal, like
    MembershipNotFoundError: whoever is asking has already proved who
    they are, so being told that one of their own sessions has already
    ended reveals nothing.
    """

    detail = "Session not found"

    def __init__(self, user_id: int, session_id: object) -> None:
        super().__init__(f"Session {session_id} is not live for user {user_id}")
        self.user_id = user_id
        self.session_id = session_id


class WorkspaceNotFoundError(AppError):
    """No workspace with that id is visible to this user.

    Deliberately the same error whether the workspace does not exist, has
    been cancelled, or belongs to somebody else. Distinguishing them would
    turn the id in the URL into a way of asking which businesses have
    accounts here, which is not a question a stranger gets to ask.
    """

    detail = "Workspace not found"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Workspace not found or not accessible: {workspace_id}")
        self.workspace_id = workspace_id


class SlugAlreadyExistsError(AppError):
    """The workspace slug is taken.

    Cancelled workspaces keep their slug. It may already be in a customer's
    bookmarks or a public URL, and handing it to somebody else would let
    them inherit that.
    """

    detail = "Workspace slug already taken"

    def __init__(self, slug: str) -> None:
        super().__init__(f"Workspace slug already taken: {slug}")
        self.slug = slug


class InsufficientWorkspaceRoleError(AppError):
    """The user is a member, but their role does not permit this.

    A 403 rather than the 404 a stranger gets: this caller has already
    proved they belong here, so confirming the workspace exists tells them
    nothing they did not know.
    """

    detail = "Your role does not permit this action"

    def __init__(self, workspace_id: object, role: object) -> None:
        super().__init__(
            f"Role {role} may not perform this action in workspace {workspace_id}"
        )
        self.workspace_id = workspace_id
        self.role = role


class WorkspaceOwnershipError(AppError):
    """The account still solely owns a workspace.

    Deleting it would leave a business with no one able to administer it,
    so the owner has to hand it over first. There is nothing to hand it
    over with yet, which is the honest state of things until memberships
    can be managed.
    """

    detail = "Transfer or close your workspaces before deleting your account"

    def __init__(self, user_id: int, workspace_ids: list[object]) -> None:
        super().__init__(
            f"User {user_id} is the only owner of workspaces: {workspace_ids}"
        )
        self.user_id = user_id
        self.workspace_ids = workspace_ids


class MembershipNotFoundError(AppError):
    """That user is not a member of this workspace.

    Safe to distinguish from every other refusal, unlike the workspace
    errors above: whoever is asking has already proved they belong here,
    so being told who is and is not on their own team reveals nothing.
    """

    detail = "That user is not a member of this workspace"

    def __init__(self, workspace_id: object, user_id: int) -> None:
        super().__init__(f"User {user_id} is not a member of workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.user_id = user_id


class LastOwnerError(AppError):
    """The workspace would be left with nobody able to administer it.

    Raised for the last owner being removed, demoted, or leaving. Every
    route into a workspace's settings requires an owner, so a workspace
    without one is a business its own members are locked out of, with no
    way back in that does not involve support.
    """

    detail = "A workspace must keep at least one owner"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Workspace {workspace_id} would be left without an owner")
        self.workspace_id = workspace_id


class InvitationNotFoundError(AppError):
    """No usable invitation matches that token.

    Covers an unknown token, one whose workspace has since been closed,
    and one that was revoked. All three are the same answer for the same
    reason the workspace errors are: whoever is holding the link has not
    proved anything yet.
    """

    detail = "Invitation not found"


class InvitationExpiredError(AppError):
    """The invitation was real, and is no longer.

    Distinguished from "not found" on purpose. This is not a secret --
    the holder had a valid link -- and "your link expired, ask for
    another" is a different thing to tell somebody than "no such link".
    """

    detail = "This invitation has expired"


class InvitationAlreadyAcceptedError(AppError):
    """The invitation has been used.

    Acceptance is single-use: `accepted_at` is set once, inside the same
    transaction that creates the membership, so a link that arrives twice
    cannot produce a second one.
    """

    detail = "This invitation has already been accepted"


class InvitationNotYoursError(AppError):
    """The invitation names a different address than the account using it.

    An invitation is addressed to a person, and a forwarded link should
    not hand somebody else a seat in a workspace that was never offered
    to them.
    """

    detail = "This invitation was sent to a different email address"


class AlreadyAMemberError(AppError):
    """That person already belongs to this workspace."""

    detail = "That person is already a member of this workspace"

    def __init__(self, workspace_id: object, email: str) -> None:
        super().__init__(f"{email} is already a member of workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.email = email


class PendingInvitationExistsError(AppError):
    """An invitation to that address is already outstanding.

    Sending a second would leave two live links to one seat, and revoking
    one of them would look like revoking access when it was not. Revoke
    the first, then invite again.
    """

    detail = "An invitation to that address is already outstanding"

    def __init__(self, workspace_id: object, email: str) -> None:
        super().__init__(f"{email} already has a pending invitation to {workspace_id}")
        self.workspace_id = workspace_id
        self.email = email


class ProductNotFoundError(AppError):
    """No product with that id exists in this workspace.

    The workspace is part of the question rather than a filter on the
    answer, for the reason every other lookup here gives it: a product id
    belonging to another business is not found, which as far as this
    caller is concerned is the same as not existing.
    """

    detail = "Product not found"

    def __init__(self, workspace_id: object, product_id: object) -> None:
        super().__init__(f"Product {product_id} not found in workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.product_id = product_id


class ProductConflictError(AppError):
    """Something in the catalogue is already using one of these values.

    An external id or a SKU, both of which are unique per workspace so
    that a storefront sync can re-run without doubling the catalogue.
    Which of the two is not said, because both mean the same thing to
    whoever is looking at the form: this identifier is taken.
    """

    detail = "That external id or SKU is already used in this workspace"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Catalogue identifier already in use in {workspace_id}")
        self.workspace_id = workspace_id


class ContactNotFoundError(AppError):
    """No contact with that id exists in this workspace.

    The workspace is part of the question, not a filter applied to the
    answer: a contact id that belongs to another business is not found
    here, which is the same thing as not existing as far as this caller
    is concerned.
    """

    detail = "Contact not found"

    def __init__(self, workspace_id: object, contact_id: object) -> None:
        super().__init__(f"Contact {contact_id} not found in workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.contact_id = contact_id


class ContactAlreadyExistsError(AppError):
    """The workspace already has a contact with that phone number.

    Per workspace, deliberately. The same person can be a customer of two
    businesses using this product, and those are two contacts.
    """

    detail = "A contact with that phone number already exists"

    def __init__(self, workspace_id: object, phone_number: str) -> None:
        super().__init__(
            f"Contact {phone_number} already exists in workspace {workspace_id}"
        )
        self.workspace_id = workspace_id
        self.phone_number = phone_number


class OrderNotFoundError(AppError):
    """No order with that id exists in this workspace."""

    detail = "Order not found"

    def __init__(self, workspace_id: object, order_id: object) -> None:
        super().__init__(f"Order {order_id} not found in workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.order_id = order_id


class OrderAlreadyExistsError(AppError):
    """That external order id is already in this workspace.

    Unique per workspace so a storefront sync can re-run without
    duplicating somebody's order -- and so that two orders can never both
    claim to be #1042.
    """

    detail = "An order with that external id already exists"

    def __init__(self, workspace_id: object, external_id: object) -> None:
        super().__init__(f"Order {external_id} already exists in {workspace_id}")
        self.workspace_id = workspace_id
        self.external_id = external_id


class OrderNotConfirmableError(AppError):
    """The order cannot be confirmed from where it is.

    Confirming is a step forward from `pending`, not a way to undo a
    cancellation or to re-confirm something already shipped. Said plainly
    rather than accepted silently, because an agent pressing the button on
    a cancelled order has misread the screen and should be told so.
    """

    detail = "Only a pending order can be confirmed"

    def __init__(self, order_id: object, status: object) -> None:
        super().__init__(f"Order {order_id} is {status} and cannot be confirmed")
        self.order_id = order_id
        self.status = status


class ConversationNotFoundError(AppError):
    """No conversation with that id exists in this workspace."""

    detail = "Conversation not found"

    def __init__(self, workspace_id: object, conversation_id: object) -> None:
        super().__init__(
            f"Conversation {conversation_id} not found in workspace {workspace_id}"
        )
        self.workspace_id = workspace_id
        self.conversation_id = conversation_id


class ConversationAlreadyOpenError(AppError):
    """That contact already has a thread that is not closed.

    One live conversation per person per channel. Two would split a
    customer's history down the middle, with half of it in an inbox row
    nobody is looking at.
    """

    detail = "That contact already has an open conversation"

    def __init__(self, contact_id: object) -> None:
        super().__init__(f"Contact {contact_id} already has an open conversation")
        self.contact_id = contact_id


class ConversationClosedError(AppError):
    """The conversation is closed, and this needs it not to be.

    Reopening is a decision somebody makes rather than something a reply
    does silently: a closed thread is a resolved one, and an agent typing
    into it should be told they are reopening it.
    """

    detail = "This conversation is closed. Reopen it first"

    def __init__(self, conversation_id: object) -> None:
        super().__init__(f"Conversation {conversation_id} is closed")
        self.conversation_id = conversation_id


class EcommerceProviderError(AppError):
    """The storefront refused, failed, or is not configured.

    Whatever it said goes to the log. What reaches the client is that the
    shop could not be reached -- a provider's error text is written for
    whoever built the integration, not for the person who pressed
    "connect".
    """

    detail = "The storefront could not be reached right now"


class StorefrontNotConnectedError(AppError):
    """This workspace has no storefront connected."""

    detail = "No storefront is connected to this workspace"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Workspace {workspace_id} has no storefront")
        self.workspace_id = workspace_id


class StorefrontAlreadyConnectedError(AppError):
    """A storefront is already connected, here or somewhere else.

    Also the answer when the shop belongs to a different workspace. The
    two are not distinguished, for the reason the WhatsApp version gives:
    saying which would confirm that a given shop uses this platform, to
    somebody who only had to guess its domain.
    """

    detail = "A storefront is already connected"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Storefront already connected for workspace {workspace_id}")
        self.workspace_id = workspace_id


class EncryptionUnavailableError(AppError):
    """A secret cannot be encrypted or decrypted right now.

    Configuration rather than a request: no key is set, the key is
    malformed, or a stored value does not authenticate against it. The
    client is told the integration is unavailable, because none of the
    three is anything they can do something about, and the detail belongs
    in the log.
    """

    detail = "This integration is not available right now"


class MessagingProviderError(AppError):
    """The messaging provider refused, failed, or could not be reached.

    Whatever it said goes to the log. What reaches the client is that the
    message could not be delivered, because a provider's own error text is
    written for whoever built the integration rather than for the agent
    who pressed send.
    """

    detail = "The message could not be delivered right now"


class WhatsAppNotConnectedError(AppError):
    """This workspace has no WhatsApp number connected."""

    detail = "No WhatsApp account is connected to this workspace"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"Workspace {workspace_id} has no WhatsApp account")
        self.workspace_id = workspace_id


class InvalidWebhookError(AppError):
    """A webhook delivery did not authenticate.

    A forged delivery and a misconfigured secret look the same from here,
    and both are refused. Nothing about which it was reaches the caller.
    """

    detail = "Invalid webhook signature"


class WhatsAppAlreadyConnectedError(AppError):
    """A WhatsApp number is already connected to this workspace.

    Also the answer when the number belongs to a different workspace. The
    two are not distinguished on purpose: saying which would confirm that
    a given business number is in use on this platform, to somebody who
    only had to guess it.
    """

    detail = "A WhatsApp account is already connected"

    def __init__(self, workspace_id: object) -> None:
        super().__init__(f"WhatsApp already connected for workspace {workspace_id}")
        self.workspace_id = workspace_id


class KnowledgeSourceNotFoundError(AppError):
    """No such source, in this workspace.

    The same answer whether it does not exist or belongs to somebody else,
    for the reason every other lookup gives it: telling those apart makes
    an id in a URL a way of asking what other businesses have stored.
    """

    detail = "Knowledge source not found"

    def __init__(self, workspace_id: object, source_id: object) -> None:
        super().__init__(
            f"Knowledge source {source_id} not in workspace {workspace_id}"
        )
        self.workspace_id = workspace_id
        self.source_id = source_id


class KnowledgeDocumentNotFoundError(AppError):
    detail = "Knowledge document not found"

    def __init__(self, workspace_id: object, document_id: object) -> None:
        super().__init__(f"Document {document_id} not in workspace {workspace_id}")
        self.workspace_id = workspace_id
        self.document_id = document_id


class DocumentAlreadyIngestedError(AppError):
    """This exact text is already in the knowledge base.

    Refused rather than stored twice. Two copies of a policy do not make
    the assistant twice as sure of it; they make every answer cite the
    same thing twice and crowd out the evidence that would have been
    second.
    """

    detail = "This content is already in the knowledge base"

    def __init__(self, workspace_id: object, content_hash: object) -> None:
        super().__init__(f"Content {content_hash} already ingested in {workspace_id}")
        self.workspace_id = workspace_id
        self.content_hash = content_hash


class UnreadableDocumentError(AppError):
    """The upload arrived but no text could be got out of it.

    A scanned PDF is the ordinary case: it is pages of images, and reading
    it needs OCR, which the MVP does not do. Said plainly, because "it
    failed" would send somebody looking for a bug rather than for a
    different copy of the file.
    """

    detail = "No text could be read from this document"

    def __init__(self, reason: str) -> None:
        # The reason is the client's message here, unlike everywhere else
        # in this file. It is advice about a file they are holding -- "this
        # is a scan, it needs OCR" -- and nothing in it is internal.
        super().__init__(reason, detail=reason)
        self.reason = reason


class UnsupportedDocumentTypeError(AppError):
    """A file of a kind the MVP does not read.

    Refused at the door rather than stored as a document that will never
    become ready. The plan's list is PDF and plain text; a spreadsheet or
    a Word file is a later phase and not a bug.
    """

    detail = "Only PDF and plain text files can be ingested"

    def __init__(self, content_type: object) -> None:
        super().__init__(f"Unsupported document type {content_type}")
        self.content_type = content_type


class EmbeddingProviderError(AppError):
    """The embedding provider refused, failed, or is not configured.

    Whatever it said goes to the log. What reaches the client is that the
    document could not be processed -- a provider's error text is written
    for whoever built the integration, not for the business uploading a
    price list.
    """

    detail = "The knowledge base could not be updated right now"


class ReplyProviderError(AppError):
    """The language model refused, failed, or is not configured.

    Raised only where it is caught: the AI pipeline records a `failed`
    decision and leaves the customer's message untouched, because a model
    being down must never be able to lose somebody's question.
    """

    detail = "The assistant is unavailable right now"


class UnknownTimezoneError(AppError):
    """A timezone nobody has heard of.

    Refused rather than quietly falling back to UTC. A dashboard showing a
    shop in Karachi its days measured from London midnight is wrong in a
    way nobody notices until somebody counts by hand.
    """

    detail = "Unknown timezone"

    def __init__(self, name: object) -> None:
        super().__init__(
            f"Unknown timezone {name!r}", detail=f"Unknown timezone: {name}"
        )
        self.name = name


class InvalidDateRangeError(AppError):
    """A range that is backwards, or longer than anything gets scanned for.

    Refused rather than clamped. A dashboard silently showing a different
    period from the one it was asked for is worse than one that says the
    request made no sense.
    """

    detail = "Invalid date range"

    def __init__(self, reason: str) -> None:
        super().__init__(reason, detail=reason)
        self.reason = reason
