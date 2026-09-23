/**
 * Pure eligibility helpers for the uploader-only "Send Association Request"
 * action on the record detail page.
 *
 * Association requests stay strictly human-in-the-loop: these helpers only
 * decide whether the *button* may be shown for a contributor. Creation
 * itself always goes through the existing POST /associations/ endpoint
 * (backend enforces uploader authorization + duplicate prevention).
 */

export type ContributorLike = Record<string, unknown>;
export type AssocRequestLike = Record<string, unknown>;

/** Request statuses that mean "already covered — do not send another". */
const LIVE_STATUSES = new Set([
  'PENDING',
  'CLARIFICATION_REQUESTED',
  'ADMIN_REVIEW',
  'ACCEPTED',
  'APPROVED',
]);

/** Live statuses that are still awaiting the recipient's decision. */
const AWAITING_STATUSES = new Set([
  'PENDING',
  'CLARIFICATION_REQUESTED',
  'ADMIN_REVIEW',
]);

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function requestStatus(row: AssocRequestLike): string {
  return String(row['status'] ?? '').toUpperCase();
}

function requestRecordId(row: AssocRequestLike): string | null {
  return nonEmptyString(row['record_id']);
}

/** Recipient identifiers carried by an association row (API field names). */
function requestRecipientKeys(row: AssocRequestLike): string[] {
  const keys: string[] = [];
  for (const field of ['recipient_id', 'recipient_faculty_id', 'target_faculty_id']) {
    const value = nonEmptyString(row[field]);
    if (value) keys.push(value);
  }
  return keys;
}

/** Resolved college identifiers carried by a contributor row. */
function contributorKeys(contributor: ContributorLike): string[] {
  const keys: string[] = [];
  const userId = nonEmptyString(contributor['user_id']);
  const facultyId = nonEmptyString(contributor['faculty_id']);
  if (userId) keys.push(userId);
  if (facultyId) keys.push(facultyId);
  return keys;
}

/**
 * Find a live (pending/accepted/approved/...) request already covering this
 * contributor on this record, if any. Matching is by record id plus any
 * shared recipient identifier (user id or faculty id).
 */
export function liveRequestFor(
  contributor: ContributorLike,
  recordId: string,
  requests: AssocRequestLike[],
): AssocRequestLike | undefined {
  const keys = new Set(contributorKeys(contributor));
  if (keys.size === 0) return undefined;
  return requests.find((row) => {
    if (requestRecordId(row) !== recordId) return false;
    if (!LIVE_STATUSES.has(requestStatus(row))) return false;
    return requestRecipientKeys(row).some((key) => keys.has(key));
  });
}

export type AssocSendState = 'sendable' | 'pending' | 'accepted' | 'ineligible';

/**
 * UI state for one contributor row:
 * - 'sendable'  → show "Send Association Request"
 * - 'pending'   → show "Request Sent" (awaiting recipient)
 * - 'accepted'  → show "Association Accepted"
 * - 'ineligible' → show no action
 */
export function associationSendState(
  contributor: ContributorLike,
  opts: { currentUserId: string | null; isUploader: boolean; recordId: string; requests: AssocRequestLike[] },
): AssocSendState {
  if (!opts.isUploader) return 'ineligible';
  if (contributor['contributor_type'] !== 'INTERNAL_FACULTY') return 'ineligible';
  if (contributor['is_external']) return 'ineligible';
  // Bug 8: deactivated faculty can never receive association requests
  // (backend rejects creation with 422; the button is hidden as well).
  // is_active is None for unresolved/external rows — those are already
  // ineligible via the checks above; only an explicit false hides here.
  if (contributor['is_active'] === false) return 'ineligible';
  const facultyId = nonEmptyString(contributor['faculty_id']);
  const userId = nonEmptyString(contributor['user_id']);
  if (!facultyId || !userId) return 'ineligible';
  if (opts.currentUserId && userId === opts.currentUserId) return 'ineligible';
  const live = liveRequestFor(contributor, opts.recordId, opts.requests);
  if (live) {
    return AWAITING_STATUSES.has(requestStatus(live)) ? 'pending' : 'accepted';
  }
  return 'sendable';
}

/** Convenience predicate: may the send button be shown? */
export function canSendAssociationRequest(
  contributor: ContributorLike,
  opts: { currentUserId: string | null; isUploader: boolean; recordId: string; requests: AssocRequestLike[] },
): boolean {
  return associationSendState(contributor, opts) === 'sendable';
}
