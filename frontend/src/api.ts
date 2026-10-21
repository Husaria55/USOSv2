export type Role = "STUDENT" | "LECTURER" | "ADMIN";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  index_no: string | null;
  program_id: number | null;
  semester: number | null;
  title: string | null;
}

export interface Term { id: number; code: string; starts_on: string; ends_on: string }
export interface Program { id: number; code: string; name: string }
export interface MeetingT { id: number; weekday: number; start: string; end: string; parity: "ALL" | "ODD" | "EVEN"; room: string | null; room_id: number | null }
export interface SectionT {
  id: number; term_id: number; code: string; kind: string; capacity: number; enrolled_count: number;
  waitlist_limit: number; waiting_count: number; meetings: MeetingT[]; lecturers: { id: number; name: string }[];
}
export interface CourseSummary { id: number; code: string; name: string; ects: number; sections: number; free_seats: number }
export interface CourseDetail {
  id: number; code: string; name: string; ects: number; description: string | null;
  prerequisites: { id: number; code: string; name: string }[]; sections: SectionT[];
}
export interface SectionStatus {
  section_id: number; state: "ENROLLED" | "WAITING" | "AVAILABLE" | "BLOCKED"; position: number | null;
  refusals: { code: string; message: string }[];
}
export interface PlanItem {
  section_id: number; course_id: number; course_code: string; course_name: string; code: string; kind: string;
  source: string; meetings: MeetingT[]; lecturers: { id: number; name: string }[];
}
export interface WaitItem {
  id: number; section_id: number; course_id: number; course_code: string; course_name: string; code: string;
  kind: string; status: string; created_at: string; resolved_at: string | null; skip_reason: string | null;
  position: number | null;
}
export interface Round { id: number; name?: string; status: string; opens_at: string; closes_at: string; program_ids?: number[] }
export interface NotificationT { id: number; type: string; message: string; created_at: string; read: boolean }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: string[] = [],
              public retryAfter?: number) {
    super(message);
  }
}

const TOKEN = "usos.token";

export const auth = {
  get token(): string | null {
    try { return localStorage.getItem(TOKEN); } catch { return null; }
  },
  set token(v: string | null) {
    try { v ? localStorage.setItem(TOKEN, v) : localStorage.removeItem(TOKEN); } catch { /* prywatne okno */ }
  },
};

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  const res = await fetch(path, {
    method: init.method ?? (init.body ? "POST" : "GET"),
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/auth/login") {
      auth.token = null;
      window.dispatchEvent(new Event("usos:logout"));
    }
    const retry = Number(res.headers.get("Retry-After")) || undefined;
    throw new ApiError(res.status, data?.code ?? "ERROR", data?.message ?? `Błąd ${res.status}`, data?.details, retry);
  }
  return data as T;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Operacja zapisu: przy przeciążeniu (429/503) ponawia sama, z odstępem z Retry-After i losowym rozrzutem,
 *  żeby tysiące przeglądarek nie wróciły w tej samej milisekundzie. */
export async function write<T>(path: string, init: { method?: string; body?: unknown },
                               onWait?: (s: number) => void): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await api<T>(path, init);
    } catch (e) {
      if (!(e instanceof ApiError) || ![429, 503].includes(e.status) || attempt >= 4) throw e;
      const wait = (e.retryAfter ?? 1) * 1000 * (1 + Math.random());
      onWait?.(Math.ceil(wait / 1000));
      await sleep(wait);
    }
  }
}

export const DAYS = ["", "pon", "wt", "śr", "czw", "pt", "sob", "nd"];
export const KINDS: Record<string, string> = { LECTURE: "wykład", EXERCISE: "ćw.", LAB: "lab", SEMINAR: "seminarium" };
export const PARITY: Record<string, string> = { ALL: "", ODD: "tyg. nieparz.", EVEN: "tyg. parz." };

export const meetingText = (m: MeetingT) =>
  `${DAYS[m.weekday]} ${m.start}–${m.end}${m.parity !== "ALL" ? `, ${PARITY[m.parity]}` : ""}${m.room ? `, s. ${m.room}` : ""}`;

export const fmtDate = (s: string) =>
  new Date(s).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
