import { describe, expect, it } from 'vitest';
import { docName, personName } from './ui';

describe('docName (Bugs 4+5)', () => {
  it('prefers the persisted uploaded filename', () => {
    expect(docName({ display_name: 'patent_application.pdf', title: 'Widget', number: 'IN123' }))
      .toBe('patent_application.pdf');
  });

  it('falls back to title, then number', () => {
    expect(docName({ title: 'Widget', number: 'IN123' })).toBe('Widget');
    expect(docName({ number: 'IN123' })).toBe('IN123');
  });

  it('never shows a raw UUID', () => {
    expect(docName({})).toBe('Untitled document');
    expect(docName(null)).toBe('Untitled document');
    expect(docName(undefined)).toBe('Untitled document');
  });
});

describe('personName (Bug 5)', () => {
  it('prefers full name, then faculty id', () => {
    expect(personName({ full_name: 'Dr Ashwin', faculty_id: 'FAC-ASHWIN' })).toBe('Dr Ashwin');
    expect(personName({ faculty_id: 'FAC-ASHWIN' })).toBe('FAC-ASHWIN');
  });

  it('never shows a raw user UUID', () => {
    expect(personName({}, 'b3c4d5e6-7890-1234-5678-9abcdef01234')).toBe('Unknown faculty');
    expect(personName({}, 'FAC-ASHWIN')).toBe('FAC-ASHWIN');
    expect(personName(null)).toBe('Unknown faculty');
  });
});
