// Knowlet — heroicons-style outline, ~14px, 1.6 stroke
const Icon = ({ d, size = 14, stroke = 1.6, fill = "none", style, children }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size}
    viewBox="0 0 24 24" fill={fill} stroke="currentColor"
    strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={style}>
    {d ? <path d={d} /> : children}
  </svg>
);

const I = {
  Search: (p) => <Icon {...p}><circle cx="11" cy="11" r="6" /><path d="m20 20-4-4" /></Icon>,
  Plus: (p) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>,
  X: (p) => <Icon {...p}><path d="M18 6 6 18M6 6l12 12" /></Icon>,
  Cog: (p) => <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33 1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></Icon>,
  Folder: (p) => <Icon {...p}><path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-10z" /></Icon>,
  FolderOpen: (p) => <Icon {...p}><path d="M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v.5M3 9.5h17l-2 7a2 2 0 0 1-2 1.5H5a2 2 0 0 1-2-2v-7z" /></Icon>,
  Doc: (p) => <Icon {...p}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" /><path d="M14 3v5h5" /></Icon>,
  ChevronR: (p) => <Icon {...p}><path d="M9 6l6 6-6 6" /></Icon>,
  ChevronD: (p) => <Icon {...p}><path d="M6 9l6 6 6-6" /></Icon>,
  Edit: (p) => <Icon {...p}><path d="M4 20h4l11-11-4-4L4 16v4z" /></Icon>,
  Eye: (p) => <Icon {...p}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></Icon>,
  Columns: (p) => <Icon {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M12 4v16" /></Icon>,
  List: (p) => <Icon {...p}><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></Icon>,
  Link: (p) => <Icon {...p}><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" /></Icon>,
  Sparkles: (p) => <Icon {...p}><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></Icon>,
  Inbox: (p) => <Icon {...p}><path d="M3 13h4l2 3h6l2-3h4M3 13l2-7h14l2 7M3 13v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6" /></Icon>,
  Cards: (p) => <Icon {...p}><rect x="3" y="6" width="14" height="14" rx="2" /><path d="M7 2h14v14" /></Icon>,
  Mining: (p) => <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></Icon>,
  Expand: (p) => <Icon {...p}><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></Icon>,
  Send: (p) => <Icon {...p}><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4z" /></Icon>,
  Tag: (p) => <Icon {...p}><path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><circle cx="7" cy="7" r=".8" /></Icon>,
  ExtLink: (p) => <Icon {...p}><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></Icon>,
  Save: (p) => <Icon {...p}><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" /></Icon>,
  Copy: (p) => <Icon {...p}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></Icon>,
  NewNote: (p) => <Icon {...p}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" /><path d="M17 3v4M15 5h4" /></Icon>,
  Refresh: (p) => <Icon {...p}><path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15.5 6.3L3 16" /><path d="M3 21v-5h5" /></Icon>,
  At: (p) => <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8" /></Icon>,
  Slash: (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M8 16 16 8" /></Icon>,
  Quote: (p) => <Icon {...p}><path d="M3 21c0-3 1-6 5-9V5H4v6h3M14 21c0-3 1-6 5-9V5h-4v6h3" /></Icon>,
  Bold: (p) => <Icon {...p}><path d="M6 4h7a4 4 0 0 1 0 8H6zM6 12h8a4 4 0 0 1 0 8H6z" /></Icon>,
  Italic: (p) => <Icon {...p}><path d="M19 4h-9M14 20H5M15 4 9 20" /></Icon>,
  Strike: (p) => <Icon {...p}><path d="M3 12h18M8 6h6a3 3 0 0 1 3 3M8 18h6a3 3 0 0 0 3-3" /></Icon>,
  Code: (p) => <Icon {...p}><path d="m16 18 6-6-6-6M8 6l-6 6 6 6" /></Icon>,
  Highlight: (p) => <Icon {...p}><path d="M9 11l-4 4v3h3l4-4M12 8l4 4M15 5l4 4-7 7-4-4z" /></Icon>,
  Trash: (p) => <Icon {...p}><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></Icon>,
  Send2: (p) => <Icon {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>,
  Loader: (p) => <Icon {...p}><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" /></Icon>,
  Lightning: (p) => <Icon {...p}><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" /></Icon>,
  Question: (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.7-2.5 2-2.5 4M12 17h.01" /></Icon>,
  Check: (p) => <Icon {...p}><path d="m5 12 5 5L20 7" /></Icon>,
  CheckSm: (p) => <Icon {...p}><path d="m4 12 5 5L20 7" /></Icon>,
  Square: (p) => <Icon {...p}><rect x="4" y="4" width="16" height="16" rx="2" /></Icon>,
  CheckSquare: (p) => <Icon {...p}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="m9 12 2.5 2.5L16 9.5" /></Icon>,
  History: (p) => <Icon {...p}><path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 8v4l3 2" /></Icon>,
  ArrowLeft: (p) => <Icon {...p}><path d="M19 12H5M12 5l-7 7 7 7" /></Icon>,
  ArrowRight: (p) => <Icon {...p}><path d="M5 12h14M12 5l7 7-7 7" /></Icon>,
  ArrowUR: (p) => <Icon {...p}><path d="M7 17 17 7M9 7h8v8" /></Icon>,
  Map: (p) => <Icon {...p}><path d="m1 6 7-3 8 3 7-3v15l-7 3-8-3-7 3zM8 3v15M16 6v15" /></Icon>,
  Calendar: (p) => <Icon {...p}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></Icon>,
  Sun: (p) => <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5" /></Icon>,
  Moon: (p) => <Icon {...p}><path d="M21 13a9 9 0 1 1-10-10 7 7 0 0 0 10 10z" /></Icon>,
  Monitor: (p) => <Icon {...p}><rect x="2" y="4" width="20" height="13" rx="2" /><path d="M8 21h8M12 17v4" /></Icon>,
  Filter: (p) => <Icon {...p}><path d="M3 4h18l-7 9v6l-4 2v-8z" /></Icon>,
  Aging: (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>,
  Orphan: (p) => <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M3 3v6M21 3v6M3 21v-6M21 21v-6" /></Icon>,
  Cluster: (p) => <Icon {...p}><circle cx="6" cy="7" r="2.5" /><circle cx="18" cy="7" r="2.5" /><circle cx="12" cy="17" r="2.5" /><path d="M8 8.5 11 15.5M16 8.5 13 15.5M8 7h8" /></Icon>,
  NearDup: (p) => <Icon {...p}><rect x="3" y="3" width="13" height="13" rx="2" /><rect x="8" y="8" width="13" height="13" rx="2" /></Icon>,
  Down: (p) => <Icon {...p}><path d="M12 5v14M19 12l-7 7-7-7" /></Icon>,
  Up: (p) => <Icon {...p}><path d="M12 19V5M5 12l7-7 7 7" /></Icon>,
  Dot: (p) => <Icon {...p} fill="currentColor" stroke="none"><circle cx="12" cy="12" r="2" /></Icon>,
};

window.I = I;
window.Icon = Icon;
