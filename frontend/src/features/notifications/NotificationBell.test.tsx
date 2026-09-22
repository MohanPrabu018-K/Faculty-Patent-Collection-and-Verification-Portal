// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { NotificationBell } from './NotificationBell';

const { apiStubs } = vi.hoisted(() => ({
  apiStubs: {
    notificationsUnreadCount: vi.fn(),
    notifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
  },
}));

vi.mock('../../api/client', () => ({
  api: apiStubs,
}));

function renderBell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ITEMS = [
  { id: 'n1', type: 'association_request', priority: 'HIGH', title: 'Assoc', message: 'Please confirm', is_read: false, created_at: '2024-10-22T00:00:00' },
  { id: 'n2', type: 'verification', priority: 'MEDIUM', title: 'Verified', message: 'Done', is_read: true, created_at: '2024-10-22T00:00:00' },
];

beforeEach(() => {
  cleanup();
  apiStubs.notificationsUnreadCount.mockReset();
  apiStubs.notifications.mockReset();
  apiStubs.markNotificationRead.mockReset();
  apiStubs.markAllNotificationsRead.mockReset();
  apiStubs.notificationsUnreadCount.mockResolvedValue({ unread_count: 1 });
  apiStubs.notifications.mockResolvedValue({ notifications: ITEMS, total: 2, page: 1, per_page: 8, unread_count: 1 });
  apiStubs.markNotificationRead.mockResolvedValue({});
  apiStubs.markAllNotificationsRead.mockResolvedValue({ marked_read: 1 });
});

describe('NotificationBell behavior', () => {
  it('opens the panel and lists notifications; clicking an unread item marks it read', async () => {
    const user = userEvent.setup();
    renderBell();
    await user.click(screen.getByRole('button', { name: /Notifications/ }));
    await screen.findByText('Assoc');
    expect(screen.getByText('Verified')).toBeInTheDocument();
    await user.click(screen.getByText('Assoc'));
    await waitFor(() => expect(apiStubs.markNotificationRead).toHaveBeenCalledWith('n1'));
  });

  it('mark-all-read action works and stays available', async () => {
    const user = userEvent.setup();
    renderBell();
    await user.click(screen.getByRole('button', { name: /Notifications/ }));
    await screen.findByText('Assoc');
    await user.click(screen.getByRole('button', { name: /Mark all read/ }));
    await waitFor(() => expect(apiStubs.markAllNotificationsRead).toHaveBeenCalledTimes(1));
  });
});

describe('notification popup responsive CSS guard', () => {
  it('pins the panel inside the viewport on tablet and mobile', () => {
    const cssPath = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'styles.css');
    const css = readFileSync(cssPath, 'utf-8');
    // Tablet (<=900px): fixed positioning with viewport margins.
    expect(css).toMatch(/\.notif-panel\s*\{[^}]*position:\s*fixed[^}]*left:\s*12px[^}]*right:\s*12px/s);
    // Mobile (<=640px): fixed positioning retained with a shorter top offset.
    expect(css).toMatch(/\.notif-panel\s*\{[^}]*position:\s*fixed[^}]*top:\s*112px/s);
    // Desktop default stays absolute-anchored and unchanged.
    expect(css).toMatch(/\.notif-panel\s*\{\s*position:\s*absolute;\s*right:\s*0;/);
  });
});
