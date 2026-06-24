/**
 * MARK III Mobile — Global State (Zustand)
 *
 * Lightweight global store. Server-polled data lives in React Query;
 * this store holds UI state and cross-component signals.
 */

import { create } from 'zustand';
import type { PendingCommand, ServerStatus } from '@/services/api';

interface LastNotification {
  title: string;
  body:  string;
}

interface MarkStore {
  // Connection
  pushToken:      string | null;
  setPushToken:   (t: string | null) => void;

  // Latest server status (mirrored from React Query for non-hook components)
  serverStatus:      ServerStatus | null;
  setServerStatus:   (s: ServerStatus) => void;

  // Sudo approval queue — commands received while app is open
  pendingCommands:      PendingCommand[];
  setPendingCommands:   (cmds: PendingCommand[]) => void;
  removeCommand:        (id: string) => void;

  // Last push notification received in foreground
  lastNotification:     LastNotification | null;
  setLastNotification:  (n: LastNotification) => void;
  clearNotification:    () => void;

  // Active device being inspected (for multi-device future support)
  activeDeviceId:    string | null;
  setActiveDeviceId: (id: string | null) => void;
}

export const useMarkStore = create<MarkStore>((set) => ({
  pushToken:    null,
  setPushToken: (t) => set({ pushToken: t }),

  serverStatus:    null,
  setServerStatus: (s) => set({ serverStatus: s }),

  pendingCommands:    [],
  setPendingCommands: (cmds) => set({ pendingCommands: cmds }),
  removeCommand:      (id) =>
    set((state) => ({
      pendingCommands: state.pendingCommands.filter((c) => c.id !== id),
    })),

  lastNotification:    null,
  setLastNotification: (n) => set({ lastNotification: n }),
  clearNotification:   () => set({ lastNotification: null }),

  activeDeviceId:    null,
  setActiveDeviceId: (id) => set({ activeDeviceId: id }),
}));
