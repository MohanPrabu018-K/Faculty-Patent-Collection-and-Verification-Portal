import { describe, expect, it } from 'vitest';
import {
  associationSendState,
  canSendAssociationRequest,
  liveRequestFor,
} from './associationEligibility';

const RECORD = 'rec-1';

function internal(name: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `c-${name}`,
    name,
    contributor_type: 'INTERNAL_FACULTY',
    is_external: false,
    user_id: `user-${name}`,
    faculty_id: `FAC-${name}`,
    match_status: 'VERIFICATION_REQUIRED',
    ...overrides,
  };
}

const OPTS = { currentUserId: 'uploader-1', isUploader: true, recordId: RECORD, requests: [] };

describe('associationSendState', () => {
  it('1: uploader sees sendable for an unresolved internal contributor', () => {
    expect(associationSendState(internal('ashwin'), OPTS)).toBe('sendable');
    expect(canSendAssociationRequest(internal('ashwin'), OPTS)).toBe(true);
  });

  it('2: non-uploader never sees the send button', () => {
    expect(associationSendState(internal('ashwin'), { ...OPTS, isUploader: false })).toBe('ineligible');
    expect(canSendAssociationRequest(internal('ashwin'), { ...OPTS, isUploader: false })).toBe(false);
  });

  it('3: external contributor is ineligible', () => {
    const ext = internal('monika', { contributor_type: 'EXTERNAL', is_external: true, user_id: null, faculty_id: null });
    expect(associationSendState(ext, OPTS)).toBe('ineligible');
  });

  it('4: unknown contributor type is ineligible', () => {
    const unk = internal('x', { contributor_type: 'UNKNOWN', user_id: null, faculty_id: null });
    expect(associationSendState(unk, OPTS)).toBe('ineligible');
  });

  it('5: uploader cannot send to themselves', () => {
    const selfie = internal('self', { user_id: 'uploader-1', faculty_id: 'FAC-SELF' });
    expect(associationSendState(selfie, OPTS)).toBe('ineligible');
    expect(canSendAssociationRequest(selfie, OPTS)).toBe(false);
  });

  it('unresolved identity (no user_id/faculty_id) is ineligible', () => {
    const unresolved = internal('ghost', { user_id: null, faculty_id: null });
    expect(associationSendState(unresolved, OPTS)).toBe('ineligible');
  });

  it('9: each internal contributor is evaluated independently', () => {
    const a = internal('ashwin');
    const b = internal('rajashekar');
    const ext = internal('monika', { contributor_type: 'EXTERNAL', is_external: true, user_id: null, faculty_id: null });
    expect([a, b, ext].map((c) => canSendAssociationRequest(c, OPTS))).toEqual([true, true, false]);
  });

  it('existing PENDING request maps to pending state', () => {
    const requests = [{ record_id: RECORD, recipient_id: 'user-ashwin', status: 'PENDING' }];
    expect(associationSendState(internal('ashwin'), { ...OPTS, requests })).toBe('pending');
    expect(canSendAssociationRequest(internal('ashwin'), { ...OPTS, requests })).toBe(false);
    // Other contributor unaffected.
    expect(associationSendState(internal('rajashekar'), { ...OPTS, requests })).toBe('sendable');
  });

  it('existing ACCEPTED request maps to accepted state', () => {
    const requests = [{ record_id: RECORD, recipient_id: 'user-ashwin', status: 'ACCEPTED' }];
    expect(associationSendState(internal('ashwin'), { ...OPTS, requests })).toBe('accepted');
  });

  it('rejected/expired requests allow resending', () => {
    for (const status of ['REJECTED', 'NOT_ME', 'EXPIRED', 'CANCELLED']) {
      const requests = [{ record_id: RECORD, recipient_id: 'user-ashwin', status }];
      expect(associationSendState(internal('ashwin'), { ...OPTS, requests })).toBe('sendable');
    }
  });

  it('requests for other records do not block', () => {
    const requests = [{ record_id: 'other-rec', recipient_id: 'user-ashwin', status: 'PENDING' }];
    expect(associationSendState(internal('ashwin'), { ...OPTS, requests })).toBe('sendable');
  });

  it('liveRequestFor matches by faculty id alias too', () => {
    const requests = [{ record_id: RECORD, recipient_faculty_id: 'FAC-ashwin', status: 'PENDING' }];
    expect(liveRequestFor(internal('ashwin'), RECORD, requests)).toBeDefined();
  });
});
