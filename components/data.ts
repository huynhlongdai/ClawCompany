export type MenuItem = {
  key:string; icon:string; label:string; badge?:string;
};
export type MenuGroup = { label:string; items:MenuItem[] };

export const menuGroups:MenuGroup[] = [
  {label:"TỔNG QUAN", items:[
    {key:"dashboard",icon:"⌂",label:"Trang chủ"},
    {key:"inbox",icon:"▨",label:"Inbox",badge:"7"},
  ]},
  {label:"TỔ CHỨC", items:[
    {key:"companies",icon:"◇",label:"Công ty"},
    {key:"departments",icon:"▦",label:"Phòng ban & Team"},
    {key:"people",icon:"◫",label:"Nhân sự",badge:"128"},
    {key:"agents",icon:"✦",label:"AI Workforce",badge:"86"},
    {key:"org",icon:"⌘",label:"Org Map"},
  ]},
  {label:"CÔNG VIỆC", items:[
    {key:"missions",icon:"◎",label:"Missions"},
    {key:"projects",icon:"▣",label:"Dự án"},
    {key:"tasks",icon:"☑",label:"Nhiệm vụ",badge:"12"},
    {key:"workflows",icon:"⇄",label:"Workflows"},
    {key:"automations",icon:"⚡",label:"Tự động hóa"},
  ]},
  {label:"TRI THỨC", items:[
    {key:"knowledge",icon:"▤",label:"Knowledge Base"},
    {key:"sop",icon:"☷",label:"SOP Library"},
    {key:"decisions",icon:"◈",label:"Decisions"},
  ]},
  {label:"GIAO TIẾP", items:[
    {key:"conversations",icon:"◌",label:"Conversations"},
    {key:"customers",icon:"♧",label:"Khách hàng"},
  ]},
  {label:"KIỂM SOÁT", items:[
    {key:"approvals",icon:"✓",label:"Phê duyệt",badge:"5"},
    {key:"reports",icon:"▥",label:"Báo cáo"},
    {key:"analytics",icon:"⌁",label:"Analytics"},
    {key:"activity",icon:"◴",label:"Activity & Audit"},
  ]},
  {label:"NỀN TẢNG", items:[
    {key:"integrations",icon:"⛓",label:"Integrations"},
    {key:"skills",icon:"✣",label:"Skills & Tools"},
    {key:"runtime",icon:"◎",label:"OpenClaw Runtime"},
    {key:"marketplace",icon:"✳",label:"Marketplace"},
    {key:"billing",icon:"$",label:"Billing"},
    {key:"settings",icon:"⚙",label:"Cài đặt"},
  ]},
];

export type ModuleSpec = {
  title:string; description:string; tabs:string[]; action:string;
  kpis:{label:string; value:string; delta?:string}[];
  columns:string[];
  rows:(string|number)[][];
  inspectorTitle?:string;
  inspector?:[string,string][];
  features?:string[];
};

export const specs:Record<string,ModuleSpec> = {
  inbox:{
    title:"Inbox", description:"Một nơi cho mọi thông báo, mention, request và việc cần xử lý.", tabs:["All","Needs action","Mentions","System"], action:"Mark all read",
    kpis:[{label:"Unread",value:"7"},{label:"Needs action",value:"5"},{label:"Mentions",value:"2"},{label:"System",value:"4"}],
    columns:["Nguồn","Nội dung","Loại","Thời gian","Trạng thái"],
    rows:[
      ["Nina","3 quyết định cần bạn duyệt","Approval","5m","Unread"],
      ["Nova Fashion","Summer Launch có 2 task bị block","Project","18m","Unread"],
      ["Alex","Production deployment waiting for approval","Mention","25m","Unread"],
      ["OpenClaw","Gateway #1 reconnected successfully","System","1h","Read"],
    ],
    inspectorTitle:"Inbox detail",
    inspector:[["Priority","High"],["Source","Nina"],["Context","Executive"],["Related object","Approval queue"],["Assigned to","Long"]],
    features:["Filter by source/type","Batch mark read","Snooze","Convert to task","Open related object"]
  },
  companies:{
    title:"Công ty", description:"Quản lý toàn bộ công ty, business unit và cấu trúc đa công ty.", tabs:["Overview","Companies","Financial","Governance"], action:"Tạo công ty",
    kpis:[{label:"Companies",value:"4"},{label:"AI Agents",value:"143"},{label:"Humans",value:"18"},{label:"Revenue",value:"$1.03M",delta:"+16%"}],
    columns:["Công ty","Ngành","AI","Human","Projects","Revenue","Health"],
    rows:[
      ["Nova Holding","Holding",22,5,4,"$240K","Healthy"],
      ["Nova Fashion","Fashion",24,6,8,"$320K","Healthy"],
      ["Nova Media","Media",21,5,5,"$290K","Healthy"],
      ["Nova Labs","AI Products",19,4,6,"$180K","Attention"],
      ["Nova Commerce","E-commerce",17,3,7,"$240K","Healthy"],
    ],
    inspectorTitle:"Nova Fashion",
    inspector:[["CEO","Long"],["Chief of Staff","Nina"],["Departments","6"],["Members","42"],["Customers","12"],["Revenue","$320K"],["Health","Healthy"]],
    features:["Create/clone/archive company","Company-level knowledge","Company policies","Financial overview","Company health score","Cross-company staffing"]
  },
  departments:{
    title:"Phòng ban & Team", description:"Workspace riêng cho department và team, có goals, knowledge và permissions.", tabs:["Departments","Teams","Goals","Permissions"], action:"Tạo phòng ban",
    kpis:[{label:"Departments",value:"8"},{label:"Teams",value:"21"},{label:"Members",value:"47"},{label:"Active goals",value:"13"}],
    columns:["Đơn vị","Head","Members","Projects","Docs","Goal","Access"],
    rows:[
      ["Marketing","Sophia (AI)","15","4","148","CAC < 80k","Restricted"],
      ["Technology","Alex (AI)","13","6","212","99.9% uptime","Private"],
      ["Operations","Emma (AI)","13","3","96","SLA > 98%","Restricted"],
      ["Content Team","Mia (AI)","5","2","32","20 video/day","Open"],
    ],
    inspectorTitle:"Marketing",
    inspector:[["Head","Sophia (AI)"],["AI members","12"],["Human members","3"],["Projects","4 active"],["Knowledge","148 docs"],["Permission","Restricted"]],
    features:["Department home","Teamspaces","Goal tracking","Member assignment","Scoped knowledge","Department reports","Permission inheritance"]
  },
  people:{
    title:"Nhân sự", description:"Quản lý Human + AI dưới cùng một organizational membership model.", tabs:["All","Human","AI","Guests","Access"], action:"Mời nhân sự",
    kpis:[{label:"Total",value:"128"},{label:"Human",value:"42"},{label:"AI",value:"86"},{label:"Guests",value:"6"}],
    columns:["Tên","Loại","Company","Department","Role","Status","Access"],
    rows:[
      ["Long","Human","Nova Holding","Executive","Owner","Online","Full"],
      ["Nina","AI Agent","Nova Holding","Executive","Chief of Staff","Online","Executive"],
      ["David","Human","Nova Holding","Finance","Head of Finance","Online","Finance"],
      ["Mia","AI Agent","Nova Fashion","Marketing","Content Lead","Busy","Marketing"],
    ],
    inspectorTitle:"Member profile",
    inspector:[["Type","Human / AI"],["Membership","Nova Holding"],["Manager","—"],["Assigned AI","Nina"],["Access level","Owner"],["Last active","Now"]],
    features:["Invite human","Assign AI assistant","Role & manager","Cross-company membership","Access review","Lifecycle/offboarding"]
  },
  agents:{
    title:"AI Workforce", description:"Registry trung tâm cho AI employee: owner, capabilities, access, lifecycle và performance.", tabs:["Registry","Performance","Access","Lifecycle","Cost"], action:"Hire AI",
    kpis:[{label:"AI Employees",value:"86"},{label:"Working",value:"62"},{label:"Idle",value:"18"},{label:"At risk",value:"4"}],
    columns:["Agent","Role","Company","Manager","Model","Success","Cost","Status"],
    rows:[
      ["Nina","Chief of Staff","Holding","Long","GPT-4.1","98%","$28.4","Online"],
      ["Sophia","CMO","Fashion","Nina","GPT-4.1","96%","$21.2","Online"],
      ["Mia","Content Lead","Fashion","Sophia","Gemini 1.5","94%","$18.4","Working"],
      ["Alex","CTO","Labs","Nina","Claude 3.5","97%","$24.8","Online"],
      ["Leo","Researcher","Fashion","Sophia","Claude 3.5","92%","$12.7","Idle"],
    ],
    inspectorTitle:"Mia — AI Content Lead",
    inspector:[["Lifecycle","Active"],["Owner","Sophia"],["Current work","Summer Launch"],["Success","94%"],["30d cost","$18.40"],["Runtime","OpenClaw / mia-content"],["Risk","Low"]],
    features:["Hire/pause/retire AI","Assign manager","Skills & tools","Knowledge access","Permission policy","Runtime binding","Performance & cost","Customer assignment"]
  },
  missions:{
    title:"Missions", description:"Mục tiêu cấp điều hành nối chiến lược với nhiều project và team.", tabs:["Active","Planning","At risk","Completed"], action:"Tạo Mission",
    kpis:[{label:"Active",value:"9"},{label:"At risk",value:"2"},{label:"Projects",value:"27"},{label:"Progress",value:"68%"}],
    columns:["Mission","Owner","Teams","Projects","Progress","Status","Target"],
    rows:[
      ["Launch Gen Z Beauty Brand","Nina","4","4","78%","On track","Sep 30"],
      ["AI Video Content Factory","Sophia","3","3","45%","Attention","Oct 15"],
      ["E-commerce Growth Q4","Emma","5","5","60%","On track","Dec 31"],
    ],
    inspectorTitle:"Mission detail",
    inspector:[["Outcome","Launch-ready brand"],["Owner","Nina"],["Companies","Nova Fashion"],["Projects","4"],["Agents","18"],["Human","2"],["Progress","78%"]],
    features:["Mission brief","Outcome & KPI","Project decomposition","Stakeholders","Dependencies","Executive updates","Decision log"]
  },
  projects:{
    title:"Dự án", description:"Workspace thực thi: team, tasks, files, outputs, reports và execution trace.", tabs:["All","Board","Timeline","Portfolio"], action:"Tạo dự án",
    kpis:[{label:"Active",value:"27"},{label:"At risk",value:"3"},{label:"Blocked",value:"2"},{label:"AI cost",value:"$842"}],
    columns:["Dự án","Company","Owner","Progress","Status","Deadline","AI Cost"],
    rows:[
      ["Launch Gen Z Beauty Brand","Nova Fashion","Nina","78%","On track","Sep 30","$31.42"],
      ["Summer Dress Campaign","Nova Fashion","Sophia","68%","On track","Sep 12","$18.80"],
      ["OpenClaw Marketplace","Nova Labs","Alex","20%","Planning","Dec 31","$44.20"],
    ],
    inspectorTitle:"Project detail",
    inspector:[["Owner","Nina"],["Agents","8"],["Humans","2"],["Tasks","47"],["Blocked","1"],["AI cost","$31.42"],["Mission","Gen Z Beauty Brand"]],
    features:["Overview","Task board","Team & roles","Files/artifacts","Knowledge scope","Reports","Activity trace","Runtime mappings"]
  },
  workflows:{
    title:"Workflows", description:"Thiết kế quy trình nhiều bước giữa human, AI, tools và approvals.", tabs:["All","Builder","Runs","Templates"], action:"Tạo workflow",
    kpis:[{label:"Workflows",value:"18"},{label:"Running",value:"6"},{label:"Runs today",value:"132"},{label:"Success",value:"96.8%"}],
    columns:["Workflow","Trigger","Steps","Owner","Runs","Success","Status"],
    rows:[
      ["Product Launch","Manual / API","12","Emma","48","97%","Active"],
      ["Content Production","Task event","9","Mia","312","96%","Active"],
      ["Client Onboarding","Customer created","14","Nina","27","100%","Active"],
    ],
    inspectorTitle:"Workflow inspector",
    inspector:[["Trigger","Task event"],["Steps","9"],["AI steps","5"],["Human approvals","1"],["Tools","3"],["Last run","4m ago"]],
    features:["Visual builder","Conditional branches","Agent steps","Human approval steps","Tool calls","Retries","Run history","Templates"]
  },
  automations:{
    title:"Tự động hóa", description:"Recurring jobs, scheduled actions và condition watches.", tabs:["All","Scheduled","Condition Watch","History"], action:"Tạo automation",
    kpis:[{label:"Active",value:"18"},{label:"Paused",value:"2"},{label:"Runs today",value:"61"},{label:"Failures",value:"1"}],
    columns:["Automation","Type","Schedule","Owner","Last run","Next","Status"],
    rows:[
      ["Daily Executive Brief","Scheduled","08:00 daily","Nina","Success","Tomorrow 08:00","Active"],
      ["Sales Drop Alert","Condition watch","Hourly","Emma","2h ago","1h","Active"],
      ["Weekly Customer Report","Scheduled","Fri 17:00","Lisa","Success","Sep 11","Active"],
    ],
    inspectorTitle:"Automation detail",
    inspector:[["Owner","Nina"],["Type","Scheduled"],["Schedule","08:00 daily"],["Runtime","OpenClaw"],["Last result","Success"],["Notifications","CEO"]],
    features:["Schedule","Condition watch","Run history","Retry policy","Notifications","Runtime mapping","Pause/resume"]
  },
  knowledge:{
    title:"Knowledge Base", description:"Tri thức có scope và permission theo organization/company/department/team/project/agent.", tabs:["Browse","Search","Sources","Access"], action:"Tải tài liệu",
    kpis:[{label:"Documents",value:"1,284"},{label:"Indexed",value:"1,276"},{label:"Sources",value:"43"},{label:"Restricted",value:"214"}],
    columns:["Tài liệu","Scope","Owner","Source","Used by","Indexed","Access"],
    rows:[
      ["Brand Guidelines v2.0","Marketing","Mia","Upload","3 projects","8m ago","Restricted"],
      ["TikTok SOP","Content Team","Sophia","Notion","8 agents","1h ago","Open"],
      ["Finance Policy","Finance","David","Drive","5 agents","2h ago","Private"],
    ],
    inspectorTitle:"Document detail",
    inspector:[["Scope","Nova Fashion / Marketing"],["Owner","Mia"],["Source","Upload"],["Version","2.0"],["Used by","3 projects"],["Access","Restricted"],["Last indexed","8m ago"]],
    features:["Folder tree","Semantic search","Source connectors","Versioning","Scope inheritance","Agent allowlist","Index status","Usage trace"]
  },
  sop:{
    title:"SOP Library", description:"Quy trình chuẩn có version, owner, approval và assignment tới team/agent.", tabs:["All SOPs","Draft","Approved","Archived"], action:"Tạo SOP",
    kpis:[{label:"SOPs",value:"84"},{label:"Approved",value:"71"},{label:"Draft",value:"9"},{label:"Needs review",value:"4"}],
    columns:["SOP","Department","Owner","Version","Assigned","Compliance","Status"],
    rows:[
      ["TikTok Publishing SOP","Marketing","Sophia","v3.2","8 agents","98%","Approved"],
      ["Production Deploy SOP","Technology","Alex","v2.1","6 agents","100%","Approved"],
      ["Customer Refund SOP","Operations","Emma","v1.4","4 agents","93%","Review"],
    ],
    inspectorTitle:"SOP detail",
    inspector:[["Owner","Sophia"],["Version","v3.2"],["Steps","12"],["Agents assigned","8"],["Last review","Aug 30"],["Compliance","98%"]],
    features:["Versioning","Approval workflow","Assign to teams","Mandatory steps","Checklists","Compliance score","Review schedule"]
  },
  decisions:{
    title:"Decisions", description:"Lưu toàn bộ quyết định quan trọng, bối cảnh, người duyệt và impact.", tabs:["All","Pending","Approved","Superseded"], action:"Ghi quyết định",
    kpis:[{label:"This month",value:"42"},{label:"Pending",value:"5"},{label:"Approved",value:"35"},{label:"Superseded",value:"2"}],
    columns:["Decision","Context","Owner","Requested by","Date","Status","Impact"],
    rows:[
      ["Increase Q4 Ads Budget","Nova Fashion","Long","Sophia","Sep 8","Approved","High"],
      ["Use Claude for research","AI Platform","Nina","Leo","Sep 7","Approved","Medium"],
      ["Create 5 AI engineers","Nova Labs","Long","Alex","Sep 9","Pending","High"],
    ],
    inspectorTitle:"Decision detail",
    inspector:[["Owner","Long"],["Requested by","Sophia"],["Context","Q4 campaign"],["Alternatives","3"],["Status","Approved"],["Linked project","Growth Q4"]],
    features:["Decision memo","Alternatives","Recommendation","Approval","Linked artifacts","Supersede decision","Impact review"]
  },
  conversations:{
    title:"Conversations", description:"Internal, project và customer conversations gắn với OpenClaw sessions.", tabs:["All","Internal","Projects","Customers"], action:"Bắt đầu chat",
    kpis:[{label:"Active threads",value:"32"},{label:"Customer",value:"9"},{label:"Project",value:"14"},{label:"Unread",value:"11"}],
    columns:["Conversation","Type","Participants","Context","Last message","Unread","Channel"],
    rows:[
      ["Nina ↔ Long","Internal","2","Executive","2m","0","Web"],
      ["Summer Launch","Project","8","Nova Fashion","8m","3","Web"],
      ["Lisa ↔ Acme","Customer","2","Acme Fashion","20m","1","Telegram"],
    ],
    inspectorTitle:"Conversation detail",
    inspector:[["Type","Customer"],["Agent","Lisa"],["Human","Acme admin"],["Session","cust_acme_01"],["Channel","Telegram"],["Project","Growth Q4"]],
    features:["Chat","Thread metadata","Session mapping","Channel routing","Files","Task creation","Escalation","Customer visibility"]
  },
  customers:{
    title:"Khách hàng", description:"Customer workspace, AI assignments, projects, usage, portal và billing.", tabs:["Customers","AI Assignments","Portal","Usage"], action:"Thêm khách hàng",
    kpis:[{label:"Customers",value:"38"},{label:"Active",value:"34"},{label:"MRR",value:"$18.4K"},{label:"AI assigned",value:"61"}],
    columns:["Khách hàng","Plan","AI assigned","Projects","Usage","MRR","Status"],
    rows:[
      ["Acme Fashion","AI Team","3","2","61%","$299","Active"],
      ["Orbit Studio","AI Employee","1","1","43%","$99","Active"],
      ["Nexa Commerce","AI Marketing Team","4","1","24%","$349","Trial"],
    ],
    inspectorTitle:"Acme Fashion",
    inspector:[["Plan","AI Team"],["Assigned AI","3"],["Projects","2"],["Portal","Enabled"],["Usage","61%"],["MRR","$299"],["Tenant","acme_001"]],
    features:["Customer profile","Assign AI employee","Assign AI team","Customer portal","Scoped knowledge","Usage limits","Tenant isolation","Billing link"]
  },
  approvals:{
    title:"Phê duyệt", description:"Human-in-the-loop cho spend, deploy, publish, hiring và quyền nhạy cảm.", tabs:["Queue","High risk","Resolved","Policies"], action:"Tạo policy",
    kpis:[{label:"Pending",value:"5"},{label:"High risk",value:"2"},{label:"Today",value:"17"},{label:"Avg response",value:"12m"}],
    columns:["Request","Agent","Scope","Risk","Requested","Policy","Status"],
    rows:[
      ["Deploy production","Alex","Nova Labs","High","10m","prod-deploy","Pending"],
      ["Spend $420 advertising","Sophia","Nova Fashion","High","25m","ads-spend","Pending"],
      ["Create 5 new agents","Nina","Holding","Medium","1h","agent-create","Pending"],
    ],
    inspectorTitle:"Approval request",
    inspector:[["Requester","Alex"],["Action","Deploy production"],["Risk","High"],["Policy","prod-deploy"],["Evidence","4 checks passed"],["Expires","2h"]],
    features:["Approve/reject","Require evidence","Policy engine","Escalation","Expiry","Audit trail","Runtime approval mapping"]
  },
  reports:{
    title:"Báo cáo", description:"Executive, department, project, customer và scheduled reports.", tabs:["Executive","Departments","Projects","Customers"], action:"Tạo báo cáo",
    kpis:[{label:"Reports",value:"64"},{label:"Scheduled",value:"18"},{label:"Generated today",value:"12"},{label:"Shared",value:"21"}],
    columns:["Báo cáo","Scope","Owner","Period","Generated","Shared","Status"],
    rows:[
      ["Executive Daily","Holding","Nina","Daily","Today 08:00","CEO","Ready"],
      ["Marketing Weekly","Marketing","Sophia","Weekly","Mon","Team","Ready"],
      ["Acme Weekly","Customer","Lisa","Weekly","Fri","Customer","Scheduled"],
    ],
    inspectorTitle:"Report detail",
    inspector:[["Owner","Nina"],["Scope","Holding"],["Schedule","Daily 08:00"],["Audience","CEO"],["Sources","12"],["Format","Dashboard + PDF"]],
    features:["Report builder","Scheduled generation","AI summary","Data sources","Share/export","Customer-safe view","Templates"]
  },
  analytics:{
    title:"Analytics", description:"Business + Workforce + AI Ops metrics trong cùng một analytics layer.", tabs:["Business","Workforce","AI Ops","Cost"], action:"Tạo dashboard",
    kpis:[{label:"Revenue",value:"$1.24M",delta:"+16%"},{label:"Task success",value:"94.7%"},{label:"Agent utilization",value:"72%"},{label:"AI cost",value:"$18.2K"}],
    columns:["Metric","Current","Previous","Change","Target","Status"],
    rows:[
      ["Revenue","$1.24M","$1.07M","+16%","$1.3M","On track"],
      ["Task success","94.7%","92.6%","+2.1%","95%","Near"],
      ["Avg task cost","$0.84","$0.91","-7.7%","$0.80","Improving"],
    ],
    inspectorTitle:"Metric detail",
    inspector:[["Scope","Holding"],["Period","Sep 2026"],["Source","Company DB"],["Updated","5m ago"],["Owner","Finance"]],
    features:["Custom dashboards","Drill-down","Compare periods","Targets","Alerts","Cost attribution","Agent ROI"]
  },
  activity:{
    title:"Activity & Audit", description:"Timeline đầy đủ cho changes, agent actions, tool calls, approvals và access.", tabs:["Activity","Audit","Security","Exports"], action:"Export audit",
    kpis:[{label:"Events today",value:"2,483"},{label:"Sensitive actions",value:"37"},{label:"Denied",value:"11"},{label:"Security flags",value:"2"}],
    columns:["Time","Actor","Action","Object","Result","Risk","Trace ID"],
    rows:[
      ["10:24","Mia","publish.request","TikTok #182","Pending","Medium","tr_921"],
      ["10:20","Alex","tool.exec","deploy-check","Allowed","High","tr_920"],
      ["10:18","Long","approval.approve","ads-spend","Success","High","tr_919"],
    ],
    inspectorTitle:"Audit event",
    inspector:[["Actor","Alex"],["Action","tool.exec"],["Result","Allowed"],["Policy","prod-safe"],["Session","sess_82"],["Trace ID","tr_920"]],
    features:["Filter event types","Trace agent run","Security events","Export","Retention policy","Immutable audit log"]
  },
  integrations:{
    title:"Integrations", description:"Kết nối channels, SaaS, data sources và business systems.", tabs:["All","Channels","Apps","Data","Webhooks"], action:"Thêm integration",
    kpis:[{label:"Connected",value:"18"},{label:"Channels",value:"6"},{label:"Data sources",value:"7"},{label:"Errors",value:"1"}],
    columns:["Integration","Category","Scope","Status","Last sync","Used by","Owner"],
    rows:[
      ["Telegram","Channel","Holding","Connected","Live","12 agents","Platform"],
      ["Google Drive","Data","Nova Fashion","Connected","6m","18 agents","Marketing"],
      ["Slack","Channel","Nova Labs","Connected","Live","9 agents","Technology"],
    ],
    inspectorTitle:"Integration detail",
    inspector:[["Type","Channel"],["Scope","Holding"],["Status","Connected"],["Agents","12"],["Permissions","Scoped"],["Last sync","Live"]],
    features:["Connect/disconnect","Scope integration","Credentials","Agent access","Health checks","Webhooks","Sync logs"]
  },
  skills:{
    title:"Skills & Tools", description:"Registry cho skills, tools, MCP, permissions và usage.", tabs:["Skills","Tools","MCP","Policies","Usage"], action:"Thêm skill/tool",
    kpis:[{label:"Skills",value:"42"},{label:"Tools",value:"31"},{label:"MCP servers",value:"7"},{label:"Restricted",value:"12"}],
    columns:["Tên","Type","Scope","Agents","Calls","Success","Policy"],
    rows:[
      ["tiktok-research","Skill","Marketing","8","1,284","97%","Allow"],
      ["browser","Tool","Holding","41","9,422","99%","Scoped"],
      ["company-mcp","MCP","Holding","86","18,203","99.8%","Role-based"],
    ],
    inspectorTitle:"Capability detail",
    inspector:[["Type","Skill"],["Scope","Marketing"],["Agents","8"],["Version","1.4"],["Success","97%"],["Policy","Allow"]],
    features:["Install/update","Assign to agents","Allowlist","Secrets","MCP registry","Usage analytics","Versioning","Deprecation"]
  },
  runtime:{
    title:"OpenClaw Runtime", description:"Gateway, runtime agents, sessions, tasks, skills, plugins và approvals.", tabs:["Overview","Agents","Sessions","Tasks","Automations","Plugins","Logs"], action:"Open Control UI",
    kpis:[{label:"Gateway",value:"Healthy"},{label:"Runtime agents",value:"86"},{label:"Sessions",value:"142"},{label:"Tasks running",value:"27"}],
    columns:["Resource","Namespace","State","Count","Latency / Last","Health","Action"],
    rows:[
      ["Gateway #1","gateway","Connected","1","28ms","Healthy","Open"],
      ["Tasks ledger","tasks.*","Running","27","Live","Healthy","Inspect"],
      ["Automations","cron.*","Active","18","1 failing","Attention","Inspect"],
      ["Skills","skills.*","Enabled","38","42 installed","Healthy","Inspect"],
    ],
    inspectorTitle:"Runtime mapping",
    inspector:[["Provider","OpenClaw"],["Gateway","gateway-01"],["Protocol","WebSocket/RPC"],["Company adapter","Connected"],["Plugin bridge","Enabled"],["Approvals","Mapped"]],
    features:["Gateway health","Runtime agent mapping","Sessions","Task ledger","Automations","Skills/plugins","Approvals","Logs","Adapter health"]
  },
  marketplace:{
    title:"Marketplace", description:"Template marketplace cho AI Employee, Team, Company, Skills và Workflows.", tabs:["All","Employees","Teams","Companies","Skills","Workflows"], action:"Publish template",
    kpis:[{label:"Templates",value:"124"},{label:"Installed",value:"19"},{label:"Published",value:"7"},{label:"MRR",value:"$4.2K"}],
    columns:["Template","Type","Publisher","Installs","Rating","Price","Status"],
    rows:[
      ["TikTok Manager","Employee","Nova","328","4.8","$49/mo","Published"],
      ["Content Team","Team","Nova","142","4.9","$299/mo","Published"],
      ["AI Marketing Agency","Company","Nova","48","4.7","$999/mo","Published"],
    ],
    inspectorTitle:"Template detail",
    inspector:[["Type","Employee"],["Version","2.3"],["Skills","8"],["Tools","4"],["Installs","328"],["Price","$49/mo"]],
    features:["Template metadata","One-click deploy","Versioning","Pricing","Ratings","Publisher analytics","Private marketplace"]
  },
  billing:{
    title:"Billing", description:"Plans, usage, customer subscriptions, AI cost và margin.", tabs:["Overview","Subscriptions","Usage","Costs","Invoices"], action:"Billing settings",
    kpis:[{label:"MRR",value:"$18.4K"},{label:"Subscriptions",value:"34"},{label:"AI cost",value:"$6.8K"},{label:"Gross margin",value:"63%"}],
    columns:["Customer","Plan","MRR","Usage","AI Cost","Margin","Renewal"],
    rows:[
      ["Acme Fashion","AI Team","$299","61%","$84","72%","Oct 8"],
      ["Orbit Studio","AI Employee","$99","43%","$28","72%","Oct 2"],
      ["Nexa Commerce","AI Marketing Team","$349","24%","$46","87%","Trial"],
    ],
    inspectorTitle:"Billing detail",
    inspector:[["Plan","AI Team"],["MRR","$299"],["AI cost","$84"],["Margin","72%"],["Usage","61%"],["Renewal","Oct 8"]],
    features:["Plans","Subscription state","Usage metering","AI cost allocation","Invoices","Margin analytics","Limits & overage"]
  },
  settings:{
    title:"Cài đặt", description:"Organization, security, policy, tenant và product preferences.", tabs:["General","Security","Permissions","Tenants","Notifications"], action:"Save changes",
    kpis:[{label:"Security posture",value:"Good"},{label:"Policies",value:"23"},{label:"Tenants",value:"39"},{label:"Admins",value:"4"}],
    columns:["Setting","Category","Current","Recommended","Changed by","Updated","Status"],
    rows:[
      ["Payment approval","Security","Required","Required","Long","Today","Good"],
      ["Tenant isolation","Security","Strict","Strict","Nina","Yesterday","Good"],
      ["Agent self-provision","Agents","Disabled","Disabled","Long","Yesterday","Good"],
    ],
    inspectorTitle:"Settings policy",
    inspector:[["Tenant isolation","Strict"],["Payment approval","Required"],["Deploy approval","Required"],["Agent self-provision","Disabled"],["Audit retention","365 days"]],
    features:["Organization settings","RBAC","Approval policies","Tenant isolation","Notification preferences","Audit retention","API keys"]
  }
};