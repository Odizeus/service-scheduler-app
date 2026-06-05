// Centralized data-testid registry
export const HOME = {
  emergentLink: "home-emergent-link",
};

export const BOOKING = {
  page: "booking-page",
  serviceSelect: "booking-service-select",
  monthPrev: "booking-month-prev",
  monthNext: "booking-month-next",
  calendar: "booking-calendar",
  dayBtn: (date) => `booking-day-${date}`,
  slotBtn: (tb) => `booking-slot-${tb}`,
  fullName: "booking-input-name",
  email: "booking-input-email",
  phone: "booking-input-phone",
  address: "booking-input-address",
  description: "booking-input-description",
  submit: "booking-submit",
  confirmation: "booking-confirmation",
};

export const ADMIN = {
  loginEmail: "admin-login-email",
  loginPassword: "admin-login-password",
  loginSubmit: "admin-login-submit",
  navAppointments: "admin-nav-appointments",
  navAvailability: "admin-nav-availability",
  navBusiness: "admin-nav-business",
  navTemplates: "admin-nav-templates",
  logout: "admin-logout",

  apptStatusFilter: "admin-appt-status-filter",
  apptServiceFilter: "admin-appt-service-filter",
  apptSearch: "admin-appt-search",
  apptFromDate: "admin-appt-from",
  apptToDate: "admin-appt-to",
  apptExportCsv: "admin-appt-export-csv",
  apptRow: (id) => `admin-appt-row-${id}`,
  apptCancelBtn: (id) => `admin-appt-cancel-${id}`,
  apptCancelConfirm: "admin-appt-cancel-confirm",

  availDay: (n) => `admin-avail-day-${n}`,
  availDayStart: "admin-avail-day-start",
  availDayEnd: "admin-avail-day-end",
  availBlockMinutes: "admin-avail-block-minutes",
  availSave: "admin-avail-save",
  overrideDate: "admin-override-date",
  overrideSlot: "admin-override-slot",
  overrideAdd: "admin-override-add",
  overrideDelete: (id) => `admin-override-delete-${id}`,

  bizName: "admin-biz-name",
  bizPhone: "admin-biz-phone",
  bizEmail: "admin-biz-email",
  bizStreet: "admin-biz-street",
  bizCity: "admin-biz-city",
  bizState: "admin-biz-state",
  bizZip: "admin-biz-zip",
  bizServiceLabel: "admin-biz-service-label",
  bizServiceTypes: "admin-biz-service-types",
  bizSave: "admin-biz-save",

  tplKey: (k) => `admin-tpl-${k}`,
  tplSave: "admin-tpl-save",
};
