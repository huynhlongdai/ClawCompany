const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";

// T mặc định là any: 288 lời gọi request(...) trong file này không truyền type
// argument, nên nếu không có default chúng trả Promise<unknown> và mọi
// setState(await api...) đều là type error. Không có contract type sinh từ
// backend, nên any là mô tả trung thực hiện trạng, không phải cách né kiểu.
async function request<T = any>(path:string, init?:RequestInit):Promise<T>{
  const token = typeof window!=="undefined" ? localStorage.getItem("clawcompany_token") : null;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {"Content-Type":"application/json", ...(token?{Authorization:`Bearer ${token}`}:{ }), ...(init?.headers||{})},
    cache: "no-store",
  });
  if(!res.ok){
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Người đang đăng nhập — sidebar cần để hiện tên thật thay vì chữ ghim cứng.
  me: () => request<any>(`/auth/me`),
  dashboard: (organizationId=1) => request(`/dashboard/summary?organization_id=${organizationId}`),
  companies: (organizationId=1) => request(`/companies?organization_id=${organizationId}`),
  departments: (companyId?:number) => request(`/departments${companyId?`?company_id=${companyId}`:""}`),
  members: () => request(`/members`),
  agents: () => request(`/agents`),
  projects: () => request(`/projects`),
  tasks: () => request(`/tasks`),
  knowledge: () => request(`/knowledge`),
  approvals: () => request(`/approvals`),
  inbox: (organizationId=1) => request(`/inbox?organization_id=${organizationId}`),
  missions: () => request(`/missions`),
  workflows: (organizationId=1) => request(`/workflows?organization_id=${organizationId}`),
  automations: (organizationId=1) => request(`/automations?organization_id=${organizationId}`),
  sops: (organizationId=1) => request(`/sops?organization_id=${organizationId}`),
  decisions: (organizationId=1) => request(`/decisions?organization_id=${organizationId}`),
  conversations: (organizationId=1) => request(`/conversations?organization_id=${organizationId}`),
  customers: (organizationId=1) => request(`/customers?organization_id=${organizationId}`),
  reports: (organizationId=1) => request(`/reports?organization_id=${organizationId}`),
  analytics: (organizationId=1) => request(`/analytics?organization_id=${organizationId}`),
  activity: (organizationId=1) => request(`/activity?organization_id=${organizationId}`),
  integrations: (organizationId=1) => request(`/integrations?organization_id=${organizationId}`),
  skills: (organizationId=1) => request(`/skills?organization_id=${organizationId}`),
  tools: (organizationId=1) => request(`/tools?organization_id=${organizationId}`),
  marketplace: (organizationId=1) => request(`/marketplace?organization_id=${organizationId}`),
  billing: () => request(`/billing/subscriptions`),
  settings: (organizationId=1) => request(`/settings?organization_id=${organizationId}`),
  ninaBrief: (organizationId=1) => request(`/nina/brief?organization_id=${organizationId}`),
  ninaCommand: (message:string, organizationId=1) => request(`/nina/command`, {method:"POST", body:JSON.stringify({organization_id:organizationId,message})}),
  vectorSearch: (query:string, organizationId=1, limit=10) => request(`/knowledge/vector-search`, {method:"POST", body:JSON.stringify({organization_id:organizationId,query,limit})}),
  policyCheck: (action:string, organizationId=1, actorMemberId?:number) => request(`/policies/check`, {method:"POST", body:JSON.stringify({organization_id:organizationId,action,actor_member_id:actorMemberId})}),
  startWorkflow: (workflowId:number, inputData:Record<string,unknown>={}) => request(`/workflow-runs/${workflowId}/start`, {method:"POST", body:JSON.stringify(inputData)}),
  advanceWorkflow: (runId:number, externalResult?:Record<string,unknown>) => request(`/workflow-runs/${runId}/advance`, {method:"POST", body:JSON.stringify(externalResult||null)}),
  runtimeRun: (runtimeAgentId:string,input:string,metadata:Record<string,unknown>={}) => request(`/runtime/run`, {method:"POST", body:JSON.stringify({runtime_agent_id:runtimeAgentId,input,metadata})}),
  usageSummary: (customerId:number) => request(`/usage/customers/${customerId}/summary`),
  invoices: (customerId?:number) => request(`/billing/invoices${customerId?`?customer_id=${customerId}`:""}`),
};
export const apiV8 = {
  hireAgent: (payload:Record<string,unknown>) => request(`/workforce/hire`, {method:"POST", body:JSON.stringify(payload)}),
  provisioningJobs: () => request(`/workforce/provisioning-jobs`),
  companyFactoryInstall: (payload:Record<string,unknown>) => request(`/company-factory/install`, {method:"POST", body:JSON.stringify(payload)}),
  companyFactoryJobs: () => request(`/company-factory/jobs`),
  ninaPlans: () => request(`/nina/plans`),
  createNinaPlan: (payload:Record<string,unknown>) => request(`/nina/plans`, {method:"POST", body:JSON.stringify(payload)}),
  delegateNinaPlan: (id:number) => request(`/nina/plans/${id}/delegate`, {method:"POST", body:JSON.stringify({execute_unassigned:false})}),
  workflowGraphVersions: (id:number) => request(`/workflows/${id}/graph/versions`),
  saveWorkflowGraph: (id:number,graph:Record<string,unknown>,publish=false) => request(`/workflows/${id}/graph`, {method:"POST", body:JSON.stringify({graph,publish})}),
  meterRules: () => request(`/usage/meter-rules`),
};

export const apiV9 = {
  controlCenter: () => request(`/v9/control-center`),
  goals: (status?:string) => request(`/v9/goals${status?`?status=${encodeURIComponent(status)}`:""}`),
  goal: (id:number) => request(`/v9/goals/${id}`),
  createGoal: (payload:Record<string,unknown>) => request(`/v9/goals`, {method:"POST", body:JSON.stringify(payload)}),
  planGoal: (id:number,payload:Record<string,unknown>={}) => request(`/v9/goals/${id}/plan`, {method:"POST", body:JSON.stringify(payload)}),
  runGoal: (id:number,payload:Record<string,unknown>={}) => request(`/v9/goals/${id}/run`, {method:"POST", body:JSON.stringify(payload)}),
  cycles: () => request(`/v9/cycles`),
  cycle: (id:number) => request(`/v9/cycles/${id}`),
  tickCycle: (id:number,captureRuntime=true) => request(`/v9/cycles/${id}/tick?capture_runtime=${captureRuntime}`, {method:"POST"}),
  autonomyPolicy: (companyId?:number) => request(`/v9/autonomy-policy${companyId?`?company_id=${companyId}`:""}`),
  saveAutonomyPolicy: (payload:Record<string,unknown>) => request(`/v9/autonomy-policy`, {method:"PUT", body:JSON.stringify(payload)}),
  budgets: () => request(`/v9/budgets`),
  budget: (id:number) => request(`/v9/budgets/${id}`),
  memorySearch: (q:string="",companyId?:number) => request(`/v9/memory/search?q=${encodeURIComponent(q)}${companyId?`&company_id=${companyId}`:""}`),
  createMemory: (payload:Record<string,unknown>) => request(`/v9/memory`, {method:"POST", body:JSON.stringify(payload)}),
  recurringOperations: () => request(`/v9/recurring-operations`),
  createRecurringOperation: (payload:Record<string,unknown>) => request(`/v9/recurring-operations`, {method:"POST", body:JSON.stringify(payload)}),
  runRecurringNow: (id:number) => request(`/v9/recurring-operations/${id}/run-now`, {method:"POST"}),
  incidents: (status?:string) => request(`/v9/incidents${status?`?status=${encodeURIComponent(status)}`:""}`),
  retryIncident: (id:number,force=false) => request(`/v9/incidents/${id}/retry`, {method:"POST", body:JSON.stringify({force})}),
  delegationTree: (companyId?:number) => request(`/v9/org/delegation-tree${companyId?`?company_id=${companyId}`:""}`),
};

export const apiV10 = {
  founderCockpit: () => request(`/v10/founder-cockpit`),
  events: (status?:string) => request(`/v10/events${status?`?status=${encodeURIComponent(status)}`:""}`),
  createEvent: (payload:Record<string,unknown>) => request(`/v10/events`, {method:"POST", body:JSON.stringify(payload)}),
  dispatchEvent: (id:number) => request(`/v10/events/${id}/dispatch`, {method:"POST"}),
  triggers: () => request(`/v10/triggers`),
  createTrigger: (payload:Record<string,unknown>) => request(`/v10/triggers`, {method:"POST", body:JSON.stringify(payload)}),
  messages: (memberId?:number) => request(`/v10/messages${memberId?`?member_id=${memberId}`:""}`),
  sendMessage: (payload:Record<string,unknown>) => request(`/v10/messages`, {method:"POST", body:JSON.stringify(payload)}),
  artifacts: (bundleKey?:string) => request(`/v10/artifacts${bundleKey?`?bundle_key=${encodeURIComponent(bundleKey)}`:""}`),
  artifact: (id:number) => request(`/v10/artifacts/${id}`),
  createArtifact: (payload:Record<string,unknown>) => request(`/v10/artifacts`, {method:"POST", body:JSON.stringify(payload)}),
  handoffArtifact: (id:number,payload:Record<string,unknown>) => request(`/v10/artifacts/${id}/handoff`, {method:"POST", body:JSON.stringify(payload)}),
  evaluateArtifact: (id:number,payload:Record<string,unknown>) => request(`/v10/artifacts/${id}/evaluate`, {method:"POST", body:JSON.stringify(payload)}),
  materializeArtifact: (id:number) => request(`/v10/artifacts/${id}/materialize`, {method:"POST"}),
  handoffs: (memberId?:number) => request(`/v10/handoffs${memberId?`?member_id=${memberId}`:""}`),
  evaluations: () => request(`/v10/evaluations`),
  slaProfiles: () => request(`/v10/sla-profiles`),
  slaIncidents: () => request(`/v10/sla-incidents`),
  runSlaCheck: () => request(`/v10/sla/check`, {method:"POST"}),
  decisionLoops: () => request(`/v10/decision-loops`),
  tickDecisionLoop: (id:number) => request(`/v10/decision-loops/${id}/tick`, {method:"POST"}),
  simulations: () => request(`/v10/simulations`),
  simulationRuns: () => request(`/v10/simulation-runs`),
  runSimulation: (id:number) => request(`/v10/simulations/${id}/run`, {method:"POST"}),
};

export const apiV11 = {
  dashboard: () => request(`/v11/delivery-dashboard`),
  repositories: () => request(`/v11/repositories`),
  repository: (id:number) => request(`/v11/repositories/${id}`),
  createRepository: (payload:Record<string,unknown>) => request(`/v11/repositories`, {method:"POST", body:JSON.stringify(payload)}),
  bindCredential: (id:number,payload:Record<string,unknown>) => request(`/v11/repositories/${id}/credentials`, {method:"POST", body:JSON.stringify(payload)}),
  createTestProfile: (id:number,payload:Record<string,unknown>) => request(`/v11/repositories/${id}/test-profiles`, {method:"POST", body:JSON.stringify(payload)}),
  pipelines: (repositoryId?:number) => request(`/v11/pipelines${repositoryId?`?repository_id=${repositoryId}`:""}`),
  createPipeline: (payload:Record<string,unknown>) => request(`/v11/pipelines`, {method:"POST", body:JSON.stringify(payload)}),
  deliveries: (status?:string) => request(`/v11/deliveries${status?`?status=${encodeURIComponent(status)}`:""}`),
  delivery: (id:number) => request(`/v11/deliveries/${id}`),
  createDelivery: (payload:Record<string,unknown>) => request(`/v11/deliveries`, {method:"POST", body:JSON.stringify(payload)}),
  prepareDelivery: (id:number) => request(`/v11/deliveries/${id}/prepare`, {method:"POST"}),
  testDelivery: (id:number) => request(`/v11/deliveries/${id}/tests`, {method:"POST"}),
  requestReview: (id:number,payload:Record<string,unknown>) => request(`/v11/deliveries/${id}/reviews`, {method:"POST", body:JSON.stringify(payload)}),
  decideReview: (id:number,payload:Record<string,unknown>) => request(`/v11/reviews/${id}/decision`, {method:"POST", body:JSON.stringify(payload)}),
  openMergeRequest: (id:number,title="") => request(`/v11/deliveries/${id}/merge-request`, {method:"POST", body:JSON.stringify({title})}),
  mergeDelivery: (id:number) => request(`/v11/deliveries/${id}/merge`, {method:"POST"}),
  cleanupDelivery: (id:number) => request(`/v11/deliveries/${id}/cleanup`, {method:"POST"}),
  rollback: (id:number,reason="") => request(`/v11/merge-requests/${id}/rollback`, {method:"POST", body:JSON.stringify({reason})}),
  rollbacks: () => request(`/v11/rollbacks`),
};

export const apiV12 = {
  dashboard: () => request(`/v12/dev-cloud-dashboard`),
  workspaces: (status?:string) => request(`/v12/workspaces${status?`?status=${encodeURIComponent(status)}`:""}`),
  createWorkspace: (payload:Record<string,unknown>) => request(`/v12/workspaces`, {method:"POST", body:JSON.stringify(payload)}),
  destroyWorkspace: (id:number) => request(`/v12/workspaces/${id}/destroy`, {method:"POST"}),
  sandboxProfiles: () => request(`/v12/sandbox-profiles`),
  createSandboxProfile: (payload:Record<string,unknown>) => request(`/v12/sandbox-profiles`, {method:"POST", body:JSON.stringify(payload)}),
  sandboxRuns: (status?:string) => request(`/v12/sandbox-runs${status?`?status=${encodeURIComponent(status)}`:""}`),
  runSandbox: (payload:Record<string,unknown>, enqueue=false) => request(`/v12/sandbox-runs?enqueue=${enqueue}`, {method:"POST", body:JSON.stringify(payload)}),
  secrets: () => request(`/v12/secrets`),
  createSecret: (payload:Record<string,unknown>) => request(`/v12/secrets`, {method:"POST", body:JSON.stringify(payload)}),
  secretGrants: () => request(`/v12/secret-grants`),
  createSecretGrant: (payload:Record<string,unknown>) => request(`/v12/secret-grants`, {method:"POST", body:JSON.stringify(payload)}),
  environments: () => request(`/v12/environments`),
  createEnvironment: (payload:Record<string,unknown>) => request(`/v12/environments`, {method:"POST", body:JSON.stringify(payload)}),
  releases: (status?:string) => request(`/v12/releases${status?`?status=${encodeURIComponent(status)}`:""}`),
  release: (id:number) => request(`/v12/releases/${id}`),
  createRelease: (payload:Record<string,unknown>) => request(`/v12/releases`, {method:"POST", body:JSON.stringify(payload)}),
  releaseGate: (id:number, environmentId:number) => request(`/v12/releases/${id}/gate?environment_id=${environmentId}`),
  deployRelease: (id:number, environmentId:number, enqueue=false) => request(`/v12/releases/${id}/deploy?enqueue=${enqueue}`, {method:"POST", body:JSON.stringify({environment_id:environmentId})}),
  createPreview: (id:number, environmentId:number, ttlMinutes=1440) => request(`/v12/releases/${id}/preview?environment_id=${environmentId}&ttl_minutes=${ttlMinutes}`, {method:"POST"}),
  deployments: (environmentId?:number) => request(`/v12/deployments${environmentId?`?environment_id=${environmentId}`:""}`),
  previews: () => request(`/v12/previews`),
  rollbackDeployment: (id:number, reason="") => request(`/v12/deployments/${id}/rollback`, {method:"POST", body:JSON.stringify({reason})}),
  automationRules: () => request(`/v12/delivery-automation-rules`),
  createAutomationRule: (payload:Record<string,unknown>) => request(`/v12/delivery-automation-rules`, {method:"POST", body:JSON.stringify(payload)}),
  triggerHandoffDelivery: (id:number) => request(`/v12/handoffs/${id}/trigger-delivery`, {method:"POST"}),
};

export const apiV13 = {
  dashboard: () => request(`/v13/engineering-dashboard`),
  executionProviders: () => request(`/v13/execution-fabric/providers`),
  gatewaySessions: (status?:string) => request(`/v13/workspace-gateway/sessions${status?`?status=${encodeURIComponent(status)}`:""}`),
  createGatewaySession: (payload:Record<string,unknown>) => request(`/v13/workspace-gateway/sessions`, {method:"POST",body:JSON.stringify(payload)}),
  gatewayWrite: (id:number,payload:Record<string,unknown>) => request(`/v13/workspace-gateway/sessions/${id}/write`, {method:"POST",body:JSON.stringify(payload)}),
  gatewayRead: (id:number,path:string) => request(`/v13/workspace-gateway/sessions/${id}/read?logical_path=${encodeURIComponent(path)}`),
  gatewaySnapshot: (id:number,payload:Record<string,unknown>) => request(`/v13/workspace-gateway/sessions/${id}/snapshot`, {method:"POST",body:JSON.stringify(payload)}),
  gatewayOperations: (sessionId?:number) => request(`/v13/workspace-gateway/operations${sessionId?`?session_id=${sessionId}`:""}`),
  graphs: () => request(`/v13/cicd/graphs`),
  createGraph: (payload:Record<string,unknown>) => request(`/v13/cicd/graphs`, {method:"POST",body:JSON.stringify(payload)}),
  validateGraph: (id:number) => request(`/v13/cicd/graphs/${id}/validate`),
  ciRuns: (status?:string) => request(`/v13/cicd/runs${status?`?status=${encodeURIComponent(status)}`:""}`),
  createCIRun: (payload:Record<string,unknown>) => request(`/v13/cicd/runs`, {method:"POST",body:JSON.stringify(payload)}),
  ciRun: (id:number) => request(`/v13/cicd/runs/${id}`),
  builds: () => request(`/v13/builds`),
  build: (id:number) => request(`/v13/builds/${id}`),
  securityReviews: () => request(`/v13/security-reviews`),
  securityReview: (id:number) => request(`/v13/security-reviews/${id}`),
  createSecurityReview: (payload:Record<string,unknown>) => request(`/v13/security-reviews`, {method:"POST",body:JSON.stringify(payload)}),
  previewRoutes: () => request(`/v13/preview-routes`),
  healthPolicies: () => request(`/v13/health-policies`),
  deploymentStrategies: () => request(`/v13/deployment-strategies`),
  healthRuns: () => request(`/v13/health-runs`),
  runDeploymentStrategy: (payload:Record<string,unknown>) => request(`/v13/deployment-strategies/run`, {method:"POST",body:JSON.stringify(payload)}),
  releaseManagerRuns: () => request(`/v13/release-manager/runs`),
  assessRelease: (payload:Record<string,unknown>) => request(`/v13/release-manager/assess`, {method:"POST",body:JSON.stringify(payload)}),
  initiatives: () => request(`/v13/initiatives`),
  createInitiative: (payload:Record<string,unknown>) => request(`/v13/initiatives`, {method:"POST",body:JSON.stringify(payload)}),
  runInitiative: (id:number,payload:Record<string,unknown>={execute_deployment:true}) => request(`/v13/initiatives/${id}/run`, {method:"POST",body:JSON.stringify(payload)}),
};

export const apiV14 = {
  runnerPools: () => request(`/v14/runner-pools`),
  runnerNodes: () => request(`/v14/runner-nodes`),
  runnerLeases: () => request(`/v14/runner-leases`),
  scannerProviders: () => request(`/v14/scanner-providers`),
  scannerRuns: () => request(`/v14/scanner-runs`),
  signatures: () => request(`/v14/evidence-signatures`),
  trafficRouters: () => request(`/v14/traffic-routers`),
  trafficShifts: () => request(`/v14/traffic-shifts`),
  metrics: (name="") => request(`/v14/telemetry/metrics${name?`?metric_name=${encodeURIComponent(name)}`:""}`),
  slos: () => request(`/v14/slos`),
  sloEvaluations: () => request(`/v14/slo-evaluations`),
  incidents: () => request(`/v14/incidents`),
  portfolioObjectives: () => request(`/v14/portfolio/objectives`),
  portfolioReviews: () => request(`/v14/portfolio/reviews`),
  reviewPortfolio: (payload:Record<string,unknown>={}) => request(`/v14/portfolio/reviews`, {method:"POST",body:JSON.stringify(payload)}),
};

export const apiV15 = {
  summary: () => request(`/v15/control-plane/summary`),
  trustAuthorities: () => request(`/v15/runner-trust/authorities`),
  runnerCertificates: () => request(`/v15/runner-trust/certificates`),
  workloadSigningKeys: () => request(`/v15/workload-signing-keys`),
  evidencePolicies: () => request(`/v15/evidence-trust/policies`),
  evidenceVerifications: () => request(`/v15/evidence-trust/verifications`),
  telemetryExporters: () => request(`/v15/telemetry/exporters`),
  secretProviders: () => request(`/v15/secret-providers`),
  secretAccessLeases: () => request(`/v15/secret-access-leases`),
  pagingRoutes: () => request(`/v15/paging/routes`),
  pagingNotifications: () => request(`/v15/paging/notifications`),
  schedulerNodes: () => request(`/v15/scheduler/nodes`),
  schedulerLeases: () => request(`/v15/scheduler/leases`),
  srePolicies: () => request(`/v15/sre/policies`),
  sreRuns: () => request(`/v15/sre/runs`),
  sreDecisions: () => request(`/v15/sre/decisions`),
  sreTick: () => request(`/v15/sre/tick`, {method:"POST"}),
  dispatchPaging: () => request(`/v15/paging/dispatch`, {method:"POST"}),
};

export const apiV16 = {
  summary: () => request(`/v16/collaboration/summary`),
  teams: () => request(`/v16/teams`),
  team: (teamId:number) => request(`/v16/teams/${teamId}`),
  createTeam: (body:any) => request(`/v16/teams`, {method:"POST", body:JSON.stringify(body)}),
  addTeamMember: (teamId:number, body:any) => request(`/v16/teams/${teamId}/members`, {method:"POST", body:JSON.stringify(body)}),
  rooms: () => request(`/v16/rooms`),
  room: (roomId:number) => request(`/v16/rooms/${roomId}`),
  openRoom: (body:any) => request(`/v16/rooms`, {method:"POST", body:JSON.stringify(body)}),
  addParticipant: (roomId:number, body:any) => request(`/v16/rooms/${roomId}/participants`, {method:"POST", body:JSON.stringify(body)}),
  speak: (roomId:number, body:any) => request(`/v16/rooms/${roomId}/turns`, {method:"POST", body:JSON.stringify(body)}),
  closeRoom: (roomId:number, body:any) => request(`/v16/rooms/${roomId}/close`, {method:"POST", body:JSON.stringify(body)}),
  delegations: () => request(`/v16/delegations`),
  overdueDelegations: () => request(`/v16/delegations/overdue`),
  propose: (body:any) => request(`/v16/delegations`, {method:"POST", body:JSON.stringify(body)}),
  acceptDelegation: (id:number, body:any) => request(`/v16/delegations/${id}/accept`, {method:"POST", body:JSON.stringify(body)}),
  rejectDelegation: (id:number, body:any) => request(`/v16/delegations/${id}/reject`, {method:"POST", body:JSON.stringify(body)}),
  deliverDelegation: (id:number, body:any) => request(`/v16/delegations/${id}/deliver`, {method:"POST", body:JSON.stringify(body)}),
  closeDelegation: (id:number, body:any) => request(`/v16/delegations/${id}/close`, {method:"POST", body:JSON.stringify(body)}),
  spaces: () => request(`/v16/knowledge-spaces`),
  createSpace: (body:any) => request(`/v16/knowledge-spaces`, {method:"POST", body:JSON.stringify(body)}),
  grants: (spaceId:number) => request(`/v16/knowledge-spaces/${spaceId}/grants`),
  createGrant: (spaceId:number, body:any) => request(`/v16/knowledge-spaces/${spaceId}/grants`, {method:"POST", body:JSON.stringify(body)}),
  permission: (spaceId:number, memberId:number) => request(`/v16/knowledge-spaces/${spaceId}/permission?member_id=${memberId}`),
  contribute: (spaceId:number, body:any) => request(`/v16/knowledge-spaces/${spaceId}/entries`, {method:"POST", body:JSON.stringify(body)}),
  search: (body:any) => request(`/v16/knowledge-mesh/search`, {method:"POST", body:JSON.stringify(body)}),
  accessLogs: () => request(`/v16/knowledge-mesh/access-logs`),
};

export const apiV17 = {
  overview: () => request(`/v17/workspace/overview`),
  orgChart: () => request(`/v17/workspace/org-chart`),
  company: (companyId:number) => request(`/v17/workspace/companies/${companyId}`),
  people: (memberType?:string, companyId?:number) => {
    const q = new URLSearchParams();
    if(memberType) q.set("member_type", memberType);
    if(companyId) q.set("company_id", String(companyId));
    const s = q.toString();
    return request<any[]>(`/v17/workspace/people${s?`?${s}`:""}`);
  },
  projects: (companyId?:number) => request<any[]>(`/v17/workspace/projects${companyId?`?company_id=${companyId}`:""}`),
  tasks: (status?:string) => request<any[]>(`/v17/workspace/tasks${status?`?status=${status}`:""}`),
  knowledge: (companyId?:number) => request<any[]>(`/v17/workspace/knowledge${companyId?`?company_id=${companyId}`:""}`),
};

export const apiV18 = {
  vocabulary: () => request<any>(`/v18/workspace/vocabulary`),
  createCompany: (body:any) => request(`/v18/workspace/companies`, {method:"POST", body:JSON.stringify(body)}),
  updateCompany: (id:number, body:any) => request(`/v18/workspace/companies/${id}`, {method:"PATCH", body:JSON.stringify(body)}),
  createDepartment: (body:any) => request(`/v18/workspace/departments`, {method:"POST", body:JSON.stringify(body)}),
  createMember: (body:any) => request(`/v18/workspace/members`, {method:"POST", body:JSON.stringify(body)}),
  updateMember: (id:number, body:any) => request(`/v18/workspace/members/${id}`, {method:"PATCH", body:JSON.stringify(body)}),
  createProject: (body:any) => request(`/v18/workspace/projects`, {method:"POST", body:JSON.stringify(body)}),
  updateProject: (id:number, body:any) => request(`/v18/workspace/projects/${id}`, {method:"PATCH", body:JSON.stringify(body)}),
  createTask: (body:any) => request(`/v18/workspace/tasks`, {method:"POST", body:JSON.stringify(body)}),
  moveTask: (id:number, status:string) => request(`/v18/workspace/tasks/${id}/move`, {method:"POST", body:JSON.stringify({status})}),
  assignTask: (id:number, assignee_member_id:number|null) => request(`/v18/workspace/tasks/${id}/assign`, {method:"POST", body:JSON.stringify({assignee_member_id})}),
  createKnowledge: (body:any) => request(`/v18/workspace/knowledge`, {method:"POST", body:JSON.stringify(body)}),
};

export const apiV19 = {
  protocol: () => request<any>(`/v19/openclaw/protocol`),
  health: () => request<any>(`/v19/openclaw/health`),
  gatewayAgents: () => request<any>(`/v19/openclaw/agents`),
  seats: () => request<any>(`/v19/openclaw/seats`),
  reconcile: () => request<any>(`/v19/openclaw/reconcile`, {method:"POST"}),
  bind: (member_id:number, runtime_agent_id:string) =>
    request(`/v19/openclaw/bind`, {method:"POST", body:JSON.stringify({member_id, runtime_agent_id})}),
  startTask: (id:number, instructions?:string) =>
    request(`/v19/tasks/${id}/start`, {method:"POST", body:JSON.stringify({instructions: instructions||null})}),
  abortTask: (id:number, back_to:string="todo") =>
    request(`/v19/tasks/${id}/abort`, {method:"POST", body:JSON.stringify({back_to})}),
  transcript: (id:number, limit=50) => request<any>(`/v19/tasks/${id}/transcript?limit=${limit}`),
  invokeTool: (body:any) => request(`/v19/openclaw/tools/invoke`, {method:"POST", body:JSON.stringify(body)}),
};

export const apiV20 = {
  streams: () => request<any>(`/v20/streams`),
  follow: (taskId:number, session_key?:string) =>
    request(`/v20/tasks/${taskId}/follow`, {method:"POST", body:JSON.stringify({session_key: session_key||null})}),
  unfollow: (taskId:number) => request(`/v20/tasks/${taskId}/unfollow`, {method:"POST"}),
  events: (taskId:number, limit=50) => request<any>(`/v20/tasks/${taskId}/events?limit=${limit}`),
  moveTask: (taskId:number, status:string, dispatch?:boolean) =>
    request<any>(`/v20/board/tasks/${taskId}/move`, {method:"POST", body:JSON.stringify({status, dispatch: dispatch ?? null})}),
  approvals: (status:string="pending", limit=50) => request<any>(`/v20/approvals/openclaw?status=${status}&limit=${limit}`),
};

export const apiV21 = {
  leases: () => request<any>(`/v21/runtime/leases`),
  resumable: () => request<any>(`/v21/runtime/resumable`),
  resume: (limit=50) => request<any>(`/v21/runtime/resume`, {method:"POST", body:JSON.stringify({limit})}),
  approvalReadiness: () => request<any>(`/v21/approvals/readiness`),
  // v23: "approved_always" maps to the gateway's allow-always standing grant
  // and is refused unless the backend opts in.
  decide: (approvalId:number, decision:"approved"|"approved_always"|"denied", note:string="") =>
    request<any>(`/v21/approvals/${approvalId}/decide`, {method:"POST", body:JSON.stringify({decision, note})}),
};

export const apiV22 = {
  streams: () => request<any>(`/v22/runtime/streams`),
  registry: () => request<any>(`/v22/runtime/registry`),
  orphans: () => request<any>(`/v22/runtime/orphans`),
  claim: (limit=50) => request<any>(`/v22/runtime/claim`, {method:"POST", body:JSON.stringify({limit})}),
};

// v24: what we missed while nobody was following, and the part of it we can
// still recover from the gateway.
export const apiV24 = {
  gaps: () => request<any>(`/v24/runtime/gaps`),
  backfillReadiness: () => request<any>(`/v24/approvals/backfill/readiness`),
  backfill: (task_id:number) => request<any>(`/v24/approvals/backfill`, {method:"POST", body:JSON.stringify({task_id})}),
};

export const apiV25 = {
  reconcileStatus: () => request<any>(`/v25/runtime/reconcile`),
  reconcile: (task_id:number) => request<any>(`/v25/runtime/reconcile`, {method:"POST", body:JSON.stringify({task_id})}),
};

// v26: is this worker actually sharing state with the rest of the cluster,
// and do its three runtime stores agree about that?
export const apiV26 = {
  fabric: () => request<any>(`/v26/runtime/fabric`),
  index: () => request<any>(`/v26/runtime/index`),
  reconnect: () => request<any>(`/v26/runtime/fabric/reconnect`, {method:"POST"}),
};

// v27: the cockpit's write half, finished. Progress is derived from the task
// board, writes can be guarded by a revision, and archiving reports its
// cascade instead of deleting rows.
export const apiV27 = {
  truth: (project_id:number) => request<any>(`/v27/projects/${project_id}/truth`),
  revision: (project_id:number) => request<any>(`/v27/revisions/project/${project_id}`),
  syncProgress: (project_id:number, expected_revision?:string) =>
    request<any>(`/v27/projects/${project_id}/progress/sync`, {method:"POST", body:JSON.stringify({expected_revision})}),
  archivePreview: (project_id:number) => request<any>(`/v27/projects/${project_id}/archive/preview`),
  archive: (project_id:number, expected_revision?:string, force?:boolean) =>
    request<any>(`/v27/projects/${project_id}/archive`, {method:"POST", body:JSON.stringify({expected_revision, force: !!force})}),
  moveTask: (task_id:number, status:string, expected_revision?:string) =>
    request<any>(`/v27/tasks/${task_id}/move`, {method:"POST", body:JSON.stringify({status, expected_revision})}),
};

// v28: the guards v27 called advisory, made binding. Every write here is a
// conditional UPDATE, so a 409 means the database refused it -- not that we
// guessed it would fail a moment earlier. Restore reverses an archive.
export const apiV28 = {
  guards: () => request<any>(`/v28/guards`),
  guardedProject: (project_id:number, expected_revision:string, values:Record<string,any>) =>
    request<any>(`/v28/guarded/projects/${project_id}`, {method:"POST", body:JSON.stringify({expected_revision, values})}),
  guardedTask: (task_id:number, expected_revision:string, values:Record<string,any>) =>
    request<any>(`/v28/guarded/tasks/${task_id}`, {method:"POST", body:JSON.stringify({expected_revision, values})}),
  guardedCompany: (company_id:number, expected_revision:string, values:Record<string,any>) =>
    request<any>(`/v28/guarded/companies/${company_id}`, {method:"POST", body:JSON.stringify({expected_revision, values})}),
  guardedMember: (member_id:number, expected_revision:string, values:Record<string,any>) =>
    request<any>(`/v28/guarded/members/${member_id}`, {method:"POST", body:JSON.stringify({expected_revision, values})}),
  restorePreview: (project_id:number) => request<any>(`/v28/projects/${project_id}/restore/preview`),
  restore: (project_id:number) => request<any>(`/v28/projects/${project_id}/restore`, {method:"POST"}),
  history: (project_id:number) => request<any>(`/v28/projects/${project_id}/history`),
};

// v29: the cascade v27 deferred and the audit feed v28 never built. Preview
// first, always: an archive that walks a whole company is the one write in
// this product where "undo" is not enough on its own.
export const apiV29 = {
  vocabulary: () => request<any>(`/v29/vocabulary`),
  archivePreview: (kind:"companies"|"departments"|"members", id:number) =>
    request<any>(`/v29/${kind}/${id}/archive/preview`),
  archive: (kind:"companies"|"departments"|"members", id:number, force?:boolean) =>
    request<any>(`/v29/${kind}/${id}/archive`, {method:"POST", body:JSON.stringify({force: !!force})}),
  restorePreview: (kind:"companies"|"departments"|"members", id:number) =>
    request<any>(`/v29/${kind}/${id}/restore/preview`),
  restore: (kind:"companies"|"departments"|"members", id:number) =>
    request<any>(`/v29/${kind}/${id}/restore`, {method:"POST"}),
  audit: (q?:{company_id?:number; entity_type?:string; entity_id?:string; category?:string[]; include_runtime?:boolean; since_hours?:number; limit?:number}) => {
    const p = new URLSearchParams();
    if(q?.company_id) p.set("company_id", String(q.company_id));
    if(q?.entity_type) p.set("entity_type", q.entity_type);
    if(q?.entity_id) p.set("entity_id", q.entity_id);
    (q?.category||[]).forEach(c=>p.append("category", c));
    if(q?.include_runtime) p.set("include_runtime", "true");
    if(q?.since_hours) p.set("since_hours", String(q.since_hours));
    if(q?.limit) p.set("limit", String(q.limit));
    const qs = p.toString();
    return request<any>(`/v29/audit${qs?`?${qs}`:""}`);
  },
  auditEntity: (entity_type:string, entity_id:string|number, limit?:number) =>
    request<any>(`/v29/audit/${entity_type}/${entity_id}${limit?`?limit=${limit}`:""}`),
};

// v30: exact revision counters, paged audit, batch board restore.
export const apiV30 = {
  modes: () => request<any>(`/v30/revisions`),
  revision: (kind:string, id:number) => request<any>(`/v30/revisions/${kind}/${id}`),
  guardedUpdate: (kind:string, id:number, expected_revision:string, values:Record<string,any>) =>
    request<any>(`/v30/guarded/${kind}/${id}`, {method:"POST", body:JSON.stringify({expected_revision, values})}),
  audit: (q?:{cursor?:number; limit?:number; company_id?:number; entity_type?:string; entity_id?:string; category?:string[]; include_runtime?:boolean; since_hours?:number}) => {
    const p = new URLSearchParams();
    if(q?.cursor) p.set("cursor", String(q.cursor));
    if(q?.limit) p.set("limit", String(q.limit));
    if(q?.company_id) p.set("company_id", String(q.company_id));
    if(q?.entity_type) p.set("entity_type", q.entity_type);
    if(q?.entity_id) p.set("entity_id", q.entity_id);
    (q?.category||[]).forEach(c=>p.append("category", c));
    if(q?.include_runtime) p.set("include_runtime", "true");
    if(q?.since_hours) p.set("since_hours", String(q.since_hours));
    const qs = p.toString();
    return request<any>(`/v30/audit${qs?`?${qs}`:""}`);
  },
  batchRestorePreview: (companyId:number) =>
    request<any>(`/v30/companies/${companyId}/projects/restore/preview`),
  batchRestore: (companyId:number) =>
    request<any>(`/v30/companies/${companyId}/projects/restore`, {method:"POST"}),
};

// v31: field-level audit values, department status, clearable columns.
export const apiV31 = {
  vocabulary: () => request("/v31/vocabulary"),
  history: (entityType: string, entityId: string | number,
            opts?: { limit?: number; cursor?: number }) => {
    const q = new URLSearchParams()
    if (opts?.limit) q.set("limit", String(opts.limit))
    if (opts?.cursor) q.set("cursor", String(opts.cursor))
    const tail = q.toString() ? `?${q.toString()}` : ""
    return request(`/v31/history/${entityType}/${entityId}${tail}`)
  },
  updateDepartment: (id: number, body: Record<string, unknown>) =>
    request(`/v31/departments/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  nameConflicts: (companyId: number) =>
    request(`/v31/companies/${companyId}/departments/name-conflicts`),
  setProjectOwner: (projectId: number, body: Record<string, unknown>) =>
    request(`/v31/projects/${projectId}/owner`, { method: "POST", body: JSON.stringify(body) }),
}

// v32: housekeeping - retention, revision adoption, runtime pool metrics.
// Ghi mac dinh la dry_run o backend; UI van truyen ro rang de khong doi y nghia
// khi ai do doi default.
export const apiV32 = {
  coverage: () => request("/v32/coverage"),
  retentionPolicy: () => request("/v32/retention/policy"),
  retentionPreview: (limit?: number) =>
    request(`/v32/retention/preview${limit ? `?limit=${limit}` : ""}`),
  prune: (body: { dry_run: boolean; limit?: number }) =>
    request("/v32/retention/prune", { method: "POST", body: JSON.stringify(body) }),
  revisionsPreview: (quietSeconds?: number) =>
    request(`/v32/revisions/preview${quietSeconds !== undefined ? `?quiet_seconds=${quietSeconds}` : ""}`),
  revisionsBackfill: (body: { dry_run: boolean; kinds?: string[]; quiet_seconds?: number }) =>
    request("/v32/revisions/backfill", { method: "POST", body: JSON.stringify(body) }),
  runtimePool: () => request("/v32/runtime/pool"),
}

// v33: recovery and retrieval. Every write defaults to a dry run server-side,
// so the panel has to opt in explicitly by sending dry_run: false.
export const apiV33 = {
  coverage: () => request("/v33/coverage"),
  memberRuntime: (memberId: number) =>
    request(`/v33/members/${memberId}/runtime`),
  memberResumePlan: (memberId: number) =>
    request(`/v33/members/${memberId}/runtime/resume-plan`),
  memberRuntimePark: (memberId: number, body: { dry_run: boolean; limit?: number }) =>
    request(`/v33/members/${memberId}/runtime/park`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  progressDrift: (companyId?: number) =>
    request(`/v33/progress/drift${companyId ? `?company_id=${companyId}` : ""}`),
  progressSync: (body: { dry_run: boolean; company_id?: number; limit?: number }) =>
    request("/v33/progress/sync", { method: "POST", body: JSON.stringify(body) }),
  knowledgeSearch: (q: string, mode = "hybrid", limit = 20) =>
    request(`/v33/knowledge/search?q=${encodeURIComponent(q)}&mode=${mode}&limit=${limit}`),
  retrievalQuality: () => request("/v33/knowledge/retrieval-quality"),
  leaseIndex: () => request("/v33/runtime/lease-index"),
  leaseIndexPrune: (body: { dry_run: boolean; limit?: number }) =>
    request("/v33/runtime/lease-index/prune", {
      method: "POST",
      body: JSON.stringify(body),
    }),
}

export const apiV34 = {
  coverage: () => request("/v34/coverage"),
  eventBacklog: (limit = 50, companyId?: number) =>
    request(`/v34/events/backlog?limit=${limit}` + (companyId ? `&company_id=${companyId}` : "")),
  eventDetail: (eventId: number) => request(`/v34/events/${eventId}`),
  eventReplay: (body: {dry_run: boolean; limit?: number; statuses?: string[]; company_id?: number}) =>
    request("/v34/events/replay", {method: "POST", body: JSON.stringify(body)}),
  runtimeUnmirrored: (limit = 50) => request(`/v34/events/runtime/unmirrored?limit=${limit}`),
  runtimeReemit: (body: {runtime_event_ids: number[]; dry_run: boolean}) =>
    request("/v34/events/runtime/reemit", {method: "POST", body: JSON.stringify(body)}),
  progressSchedules: (companyId?: number) =>
    request("/v34/progress/schedules" + (companyId ? `?company_id=${companyId}` : "")),
  progressScheduleCreate: (body: {schedule?: string; timezone?: string; limit?: number; dry_run_runs?: boolean; enabled?: boolean; company_id?: number; name?: string}) =>
    request("/v34/progress/schedules", {method: "POST", body: JSON.stringify(body)}),
  progressScheduleToggle: (operationId: number, enabled: boolean) =>
    request(`/v34/progress/schedules/${operationId}/enabled`, {method: "POST", body: JSON.stringify({enabled})}),
  grants: (includeRevoked = false) => request(`/v34/grants?include_revoked=${includeRevoked}`),
  grantsDue: (withinDays = 7) => request(`/v34/grants/due?within_days=${withinDays}`),
  grantRevoke: (body: {grant_key: string; note?: string; confirmed_cleared_upstream?: boolean}) =>
    request("/v34/grants/revoke", {method: "POST", body: JSON.stringify(body)}),
}

export const apiV35 = {
  coverage: () => request("/v35/coverage"),
  spendReport: (companyId?: number, statuses?: string) =>
    request("/v35/spend/report"
      + (companyId ? `?company_id=${companyId}` : "")
      + (statuses ? `${companyId ? "&" : "?"}statuses=${encodeURIComponent(statuses)}` : "")),
  spendRollup: (companyId?: number) =>
    request("/v35/spend/rollup" + (companyId ? `?company_id=${companyId}` : "")),
  spendOverruns: (includeWarnings = false) =>
    request(`/v35/spend/overruns?include_warnings=${includeWarnings}`),
  spendDetail: (delegationId: number) => request(`/v35/spend/delegations/${delegationId}`),
  flagOverruns: (body: {dry_run: boolean; company_id?: number; include_warnings?: boolean; limit?: number}) =>
    request("/v35/spend/flag-overruns", {method: "POST", body: JSON.stringify(body)}),
  liveReadiness: () => request("/v35/live/readiness"),
  liveSnapshot: (cursor = 0) => request(`/v35/live/snapshot?cursor=${cursor}`),
  liveEvents: (cursor = 0, limit = 100) => request(`/v35/live/events?cursor=${cursor}&limit=${limit}`),
  liveTasks: (limit = 50) => request(`/v35/live/tasks?limit=${limit}`),
  // SSE is not fetch-based: hand back an EventSource the caller must close.
  liveStream: (cursor = 0, seconds = 300) => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return null;
    return new EventSource(`${API_BASE}/v35/live/stream?cursor=${cursor}&seconds=${seconds}`,
      {withCredentials: true});
  },
}

/* v36: bốn khối mà bản thiết kế UI cần và hệ thống cũ không có nguồn —
   lịch sử chỉ số (chuỗi thời gian), lịch, số theo ngày của agent, hạn chót
   dự án. Mọi endpoint đọc đều trả kèm lời thừa nhận về nguồn dữ liệu. */
export const apiV36 = {
  coverage: () => request<any>(`/v36/coverage`),
  metricHistory: (metricKey?: string) =>
    request<any>(`/v36/metrics/history${metricKey ? `?metric_key=${encodeURIComponent(metricKey)}` : ""}`),
  snapshotMetrics: (grain: "month" | "day" = "month") =>
    request<any>(`/v36/metrics/snapshot?grain=${grain}`, {method: "POST"}),
  calendar: (days = 1) => request<any>(`/v36/calendar?days=${days}`),
  createCalendarEvent: (body: Record<string, unknown>) =>
    request<any>(`/v36/calendar`, {method: "POST", body: JSON.stringify(body)}),
  agentStats: (days = 30, agentId?: number) =>
    request<any>(`/v36/agent-stats?days=${days}${agentId ? `&agent_id=${agentId}` : ""}`),
  deriveAgentStats: (days = 30) =>
    request<any>(`/v36/agent-stats/derive?days=${days}`, {method: "POST"}),
  deadlines: (days = 30) => request<any>(`/v36/deadlines?days=${days}`),
  askNina: (message: string, timeoutSeconds = 60) =>
    request<any>(`/v36/nina/ask`,
      {method: "POST", body: JSON.stringify({message, timeout_seconds: timeoutSeconds})}),
  setDueDate: (projectId: number, dueDate: string | null) =>
    request<any>(`/v36/projects/${projectId}/due-date`,
      {method: "POST", body: JSON.stringify({due_date: dueDate})}),
};

/* WP-2.1 + WP-2.2: hồ sơ nhân sự AI.

   Một seat là ba nguồn phải khớp nhau — hàng trong Postgres, entry
   `agents.entries.<id>` trong openclaw.json, và 5 file bootstrap trong
   workspace. `seatProfile` gộp cả ba và nói rõ mỗi phần đến từ đâu.

   Ghi thì tách hai đường, đúng như bản chất của dữ liệu:
   - tab Hồ sơ/Tính cách/Công việc  -> writeSeatFile  (agents.files.set)
   - tab Năng lực/Quyền/Hạn mức     -> writeSeatConfig (config.patch)

   `expectedHash` là bắt buộc khi ghi file: thiếu nó thì server từ chối, và
   nếu hash đã cũ thì trả 409 kèm `current_hash` để tải lại. */
export const apiSeat = {
  profile: (agentId: number) => request<any>(`/agents/${agentId}/profile`),
  writeFile: (agentId: number, name: string, content: string,
              expectedHash: string | null, force = false) =>
    request<any>(`/agents/${agentId}/files/${encodeURIComponent(name)}`,
      {method: "PUT",
       body: JSON.stringify({content, expected_hash: expectedHash, force})}),
  writeConfig: (agentId: number, tab: string, values: Record<string, unknown>,
                opts: {baseHash?: string; allowRestart?: boolean; dryRun?: boolean} = {}) =>
    request<any>(`/agents/${agentId}/config`,
      {method: "PATCH",
       body: JSON.stringify({tab, values, base_hash: opts.baseHash ?? null,
                             allow_restart: !!opts.allowRestart,
                             dry_run: !!opts.dryRun})}),
};

/* WP-4.3 UI: màn hình chi tiết một công việc.

   Ba thứ mà màn hình này cần, và cả ba đều là dữ liệu thật:
   - journal      -> GET  /api/tasks/{id}/journal       (task_journal_entries)
   - contextPack  -> GET  /api/tasks/{id}/context-pack  (đúng hàm mà dispatch gọi)
   - handoff      -> POST /api/tasks/{id}/handoff       (artifact_handoffs + dispatch)

   `contextPack` cố ý gọi cùng `work_context.build_pack` mà `agent_dispatch` gọi:
   nếu màn hình xem trước hiện một thứ mà agent nhận một thứ khác thì nó không
   chỉ vô dụng, nó gây tin sai. */
export const apiTask = {
  get: (taskId: number) => request<any>(`/tasks`).then((rows: any) =>
    (rows || []).find((t: any) => t.id === taskId) || null),
  journal: (taskId: number) => request<any>(`/tasks/${taskId}/journal`),
  contextPack: (taskId: number) => request<any>(`/tasks/${taskId}/context-pack`),
  handoff: (taskId: number, body: {to_member_id: number; instructions: string;
                                   purpose?: string; dispatch?: boolean | null}) =>
    request<any>(`/tasks/${taskId}/handoff`,
      {method: "POST", body: JSON.stringify(body)}),
  dispatch: (taskId: number) =>
    request<any>(`/tasks/${taskId}/dispatch`, {method: "POST"}),
};
