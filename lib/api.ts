
import {ApiError, describeError, request, API_BASE, activeOrg, activeCompany} from "./http";
export {ApiError, describeError};

export const api = {
  // Người đang đăng nhập — sidebar cần để hiện tên thật thay vì chữ ghim cứng.
  me: () => request<any>(`/auth/me`),
  // Cờ LAB_JOBS_ENABLED của backend: 6 job nền Phòng thí nghiệm có chạy không.
  // i18n: ngôn ngữ giao diện lưu theo tài khoản.
  updateMe: (body:{locale:"vi"|"en"}) => request<any>(`/auth/me`, {method:"PATCH", body: JSON.stringify(body)}),
  labStatus: () => request<{lab_jobs_enabled:boolean; env:string; jobs:string[]}>(`/health/lab`),
  dashboard: (organizationId:number=activeOrg()) => request(`/dashboard/summary?organization_id=${organizationId}`),
  companies: (organizationId:number=activeOrg()) => request(`/companies?organization_id=${organizationId}`),
  departments: (companyId?:number) => request(`/departments${companyId?`?company_id=${companyId}`:""}`),
  members: () => request(`/members`),
  agents: () => request(`/agents`),
  projects: () => request(`/projects`),
  tasks: () => request(`/tasks`),
  knowledge: () => request(`/knowledge`),
  approvals: () => request(`/approvals`),
  inbox: (organizationId:number=activeOrg(), companyId:number|null=activeCompany()) => request(`/inbox?organization_id=${organizationId}${companyId?`&company_id=${companyId}`:""}`),
  missions: () => request(`/missions`),
  workflows: (organizationId:number=activeOrg()) => request(`/workflows?organization_id=${organizationId}`),
  automations: (organizationId:number=activeOrg()) => request(`/automations?organization_id=${organizationId}`),
  sops: (organizationId:number=activeOrg()) => request(`/sops?organization_id=${organizationId}`),
  decisions: (organizationId:number=activeOrg()) => request(`/decisions?organization_id=${organizationId}`),
  conversations: (organizationId:number=activeOrg()) => request(`/conversations?organization_id=${organizationId}`),
  customers: (organizationId:number=activeOrg()) => request(`/customers?organization_id=${organizationId}`),
  reports: (organizationId:number=activeOrg()) => request(`/reports?organization_id=${organizationId}`),
  analytics: (organizationId:number=activeOrg()) => request(`/analytics?organization_id=${organizationId}`),
  activity: (organizationId:number=activeOrg()) => request(`/activity?organization_id=${organizationId}`),
  integrations: (organizationId:number=activeOrg()) => request(`/integrations?organization_id=${organizationId}`),
  skills: (organizationId:number=activeOrg()) => request(`/skills?organization_id=${organizationId}`),
  tools: (organizationId:number=activeOrg()) => request(`/tools?organization_id=${organizationId}`),
  marketplace: (organizationId:number=activeOrg()) => request(`/marketplace?organization_id=${organizationId}`),
  billing: () => request(`/billing/subscriptions`),
  settings: (organizationId:number=activeOrg()) => request(`/settings?organization_id=${organizationId}`),
  ninaBrief: (organizationId:number=activeOrg()) => request(`/nina/brief?organization_id=${organizationId}`),
  ninaCommand: (message:string, organizationId:number=activeOrg()) => request(`/nina/command`, {method:"POST", body:JSON.stringify({organization_id:organizationId,message})}),
  vectorSearch: (query:string, organizationId:number=activeOrg(), limit=10) => request(`/knowledge/vector-search`, {method:"POST", body:JSON.stringify({organization_id:organizationId,query,limit})}),
  policyCheck: (action:string, organizationId:number=activeOrg(), actorMemberId?:number) => request(`/policies/check`, {method:"POST", body:JSON.stringify({organization_id:organizationId,action,actor_member_id:actorMemberId})}),
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
  // D2.3: phạm vi + nấc + chi tiêu thật theo seat/task/dự án; override có audit
  budgetsOverview: () => request(`/v9/budgets-overview`),
  createBudget: (payload:Record<string,unknown>) => request(`/v9/budgets`, {method:"POST", body:JSON.stringify(payload)}),
  overrideBudget: (id:number,payload:Record<string,unknown>) => request(`/v9/budgets/${id}/override`, {method:"POST", body:JSON.stringify(payload)}),
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
  // D3.1: giao việc cho phòng ban; trưởng phòng định tuyến
  routeTask: (id:number, department_id:number, reason="") => request(`/v18/workspace/tasks/${id}/route`, {method:"POST", body:JSON.stringify({department_id, reason})}),
  departmentRouting: (id:number) => request<any>(`/v18/workspace/departments/${id}/routing`),
  setDepartmentGuide: (id:number, guide:string) => request(`/v18/workspace/departments/${id}/guide`, {method:"PUT", body:JSON.stringify({guide})}),
  assignTask: (id:number, assignee_member_id:number|null) => request(`/v18/workspace/tasks/${id}/assign`, {method:"POST", body:JSON.stringify({assignee_member_id})}),
  createKnowledge: (body:any) => request(`/v18/workspace/knowledge`, {method:"POST", body:JSON.stringify(body)}),
};

export const apiV19 = {
  protocol: () => request<any>(`/v19/openclaw/protocol`),
  health: () => request<any>(`/v19/openclaw/health`),
  doctor: () => request<any>(`/v19/openclaw/doctor`),
  doctorAction: (method:string, path:string) => request<any>(path, {method}),
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
  /* D1.3 — đồ thị: cha/con, mục tiêu, task đang chặn. */
  graph: (taskId: number) => request<any>(`/tasks/${taskId}/graph`),
  addBlocker: (taskId: number, blockedBy: number) =>
    request<any>(`/tasks/${taskId}/dependencies`,
      {method: "POST", body: JSON.stringify({blocked_by_task_id: blockedBy})}),
  removeBlocker: (taskId: number, blockedBy: number) =>
    request<any>(`/tasks/${taskId}/dependencies/${blockedBy}`, {method: "DELETE"}),
  /* Chỉ trường có trong `links` bị đổi; `null` là gỡ liên kết. */
  setLinks: (taskId: number, links: {parent_task_id?: number | null; goal_id?: number | null;
                                     due_at?: string | null; acceptance_criteria?: string}) =>
    request<any>(`/tasks/${taskId}/links`, {method: "PATCH", body: JSON.stringify(links)}),
  byGoal: (goalId: number) => request<any>(`/tasks?goal_id=${goalId}`),
  /* D1.4 — mỗi lượt agent làm việc này là một hàng task_runs. */
  runs: (taskId: number) => request<any>(`/tasks/${taskId}/runs`),
  /* D2.1 — người ghi một dòng vào sổ; `@Tên` seat agent sẽ đánh thức seat đó. */
  comment: (taskId: number, summary: string) =>
    request<any>(`/tasks/${taskId}/journal`, {method: "POST", body: JSON.stringify({summary})}),
  /* D2.1 — hàng đợi đánh thức của việc này: lý do, trạng thái, vì sao bị bỏ qua. */
  wakeups: (taskId: number) => request<any>(`/tasks/wakeups?task_id=${taskId}`),
  policy: (taskId: number) => request<any>(`/tasks/${taskId}/execution-policy`),
  setPolicy: (taskId: number, stages: {type: string; participants: number[]; mode?: string}[]) =>
    request<any>(`/tasks/${taskId}/execution-policy`, {method: "PUT", body: JSON.stringify({stages})}),
  review: (taskId: number, decision: "approve" | "revise", note: string) =>
    request<any>(`/tasks/${taskId}/review`, {method: "POST", body: JSON.stringify({decision, note})}),
};

/* D1.5 + D1.6 — máy chủ MCP của ClawCompany và bảng quyền tool theo bậc ghế.
   `toolLog` đọc event bus (v10) vì mỗi lần gọi tool đã ghi `mcp.tool.called`
   hoặc `mcp.tool.denied` — không có bảng log riêng để lệch với sự thật. */
export const apiMcp = {
  tools: () => request<any>(`/mcp/tools`),
  permissions: () => request<any>(`/mcp/permissions`),
  setPermission: (body: {tool: string; level: string; role?: string; member_id?: number}) =>
    request<any>(`/mcp/permissions`, {method: "PUT", body: JSON.stringify(body)}),
  toolLog: async (limit = 40) => {
    const [called, denied] = await Promise.all([
      request<any[]>(`/v10/events?event_type=mcp.tool.called&limit=${limit}`),
      request<any[]>(`/v10/events?event_type=mcp.tool.denied&limit=${limit}`),
    ]);
    return [...(called || []), ...(denied || [])]
      .sort((a, b) => (b.id || 0) - (a.id || 0)).slice(0, limit);
  },
};

/* Lỗi từ `request` là nguyên văn body. FastAPI trả {"detail": ...}, mà detail
   có thể là chuỗi hoặc {message}. Rút ra câu người đọc được. */
export function errorText(e: any, fallback = "Thao tác thất bại"): string {
  const raw = e?.message || "";
  try {
    const body = JSON.parse(raw);
    const d = body?.detail;
    if (typeof d === "string") return d;
    if (d?.message) return d.message;
    if (Array.isArray(d)) return d.map((x: any) => x?.msg || "").filter(Boolean).join("; ");
  } catch { /* không phải JSON */ }
  return raw || fallback;
}

/* v6 — Hộp việc: hai thao tác ghi mà Hộp việc cần. Cả hai endpoint đã có từ
   lâu (approvals.py, extended.py) nhưng chưa có hàm nào ở frontend gọi tới. */
export const apiInbox = {
  resolveApproval: (id: number, status: "approved" | "rejected", resolution_note = "") =>
    request<any>(`/approvals/${id}/resolve`, {method: "POST", body: JSON.stringify({status, resolution_note})}),
  markRead: (id: number) => request<any>(`/inbox/${id}/read`, {method: "POST"}),
  // D3.5: hộp việc của tôi, gộp theo task; duyệt nhanh; chạy leo thang ngay
  mine: (status = "open") => request<any>(`/v9/inbox/mine?status=${status}`),
  setStatus: (id: number, status: "unread" | "read" | "done") => request<any>(`/v9/inbox/${id}/status`, {method: "POST", body: JSON.stringify({status})}),
  quickApprovals: () => request<any>(`/v9/approvals/quick`),
  escalateOverdue: () => request<any>(`/v9/approvals/escalate-overdue`, {method: "POST"}),
};

// D3.4: routines — cron theo múi giờ / webhook, chạy bù, tự dừng khi lỗi liên tiếp
export const apiRoutines = {
  list: () => request<any>(`/routines`),
  templates: () => request<any>(`/routines/templates`),
  get: (id: number) => request<any>(`/routines/${id}`),
  create: (body: any) => request<any>(`/routines`, {method: "POST", body: JSON.stringify(body)}),
  fromTemplate: (key: string, assignee_member_id?: number | null, department_id?: number | null) =>
    request<any>(`/routines/from-template`, {method: "POST", body: JSON.stringify({key, assignee_member_id, department_id})}),
  setEnabled: (id: number, enabled: boolean) => request<any>(`/routines/${id}`, {method: "PATCH", body: JSON.stringify({enabled})}),
  run: (id: number) => request<any>(`/routines/${id}/run`, {method: "POST"}),
  runs: (id: number) => request<any>(`/routines/${id}/runs`),
  tick: () => request<any>(`/routines/tick`, {method: "POST"}),
};

// D3.3: kế hoạch mục tiêu của Nina — duyệt / yêu cầu sửa / từ chối
export const apiStrategy = {
  goals: () => request<any>(`/strategy/goals`),
  goal: (id: number) => request<any>(`/strategy/goals/${id}`),
  requestRevision: (approvalId: number, note: string) =>
    request<any>(`/strategy/plans/${approvalId}/request-revision`, {method: "POST", body: JSON.stringify({note})}),
};

// M2: Đội ngũ — sơ đồ tổ chức, người & quyền, lời mời, trưởng phòng, mẫu công ty, CSV
export const apiTeam = {
  me: () => request<any>(`/team/me`),
  people: () => request<any>(`/team/people`),
  invite: (body: any) => request<any>(`/team/invitations`, {method: "POST", body: JSON.stringify(body)}),
  revokeInvite: (id: number) => request<any>(`/team/invitations/${id}`, {method: "DELETE"}),
  lookupInvite: (token: string) => request<any>(`/team/invitations/lookup?token=${encodeURIComponent(token)}`),
  acceptInvite: (token: string, password: string, display_name = "") =>
    request<any>(`/team/invitations/accept`, {method: "POST", body: JSON.stringify({token, password, display_name})}),
  setRole: (userId: number, role: string) => request<any>(`/team/access/${userId}`, {method: "PATCH", body: JSON.stringify({role})}),
  revokeAccess: (userId: number) => request<any>(`/team/access/${userId}`, {method: "DELETE"}),
  orgChart: (companyId?: number | null) => request<any>(`/team/org-chart${companyId ? `?company_id=${companyId}` : ""}`),
  setHead: (departmentId: number, member_id: number | null) =>
    request<any>(`/team/departments/${departmentId}/head`, {method: "PUT", body: JSON.stringify({member_id})}),
  setManager: (memberId: number, manager_id: number | null) =>
    request<any>(`/team/members/${memberId}/manager`, {method: "PUT", body: JSON.stringify({manager_id})}),
  templates: () => request<any>(`/team/templates`),
  fromTemplate: (template_key: string, company_name: string) =>
    request<any>(`/team/companies/from-template`, {method: "POST", body: JSON.stringify({template_key, company_name})}),
  importCsv: (company_id: number, csv_text: string, dry_run: boolean) =>
    request<any>(`/team/import-csv`, {method: "POST", body: JSON.stringify({company_id, csv_text, dry_run})}),
};

// M2b: nền công ty — hồ sơ pháp nhân + hiến chương, chức danh, ma trận phân quyền (tiền: USD).
const cq = (companyId?: number | null) => (companyId ? `?company_id=${companyId}` : "");
export const apiCompany = {
  profile: (companyId?: number | null) => request<any>(`/team/company-profile${cq(companyId)}`),
  saveProfile: (body: any) => request<any>(`/team/company-profile`, {method: "PUT", body: JSON.stringify(body)}),
  positions: (companyId?: number | null) => request<any>(`/team/positions${cq(companyId)}`),
  createPosition: (body: any) => request<any>(`/team/positions`, {method: "POST", body: JSON.stringify(body)}),
  updatePosition: (id: number, body: any) => request<any>(`/team/positions/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  archivePosition: (id: number) => request<any>(`/team/positions/${id}`, {method: "DELETE"}),
  positionsFromMembers: (companyId?: number | null) => request<any>(`/team/positions/from-members${cq(companyId)}`, {method: "POST"}),
  assign: (id: number, member_id: number) => request<any>(`/team/positions/${id}/seats`, {method: "POST", body: JSON.stringify({member_id})}),
  unassign: (id: number, memberId: number) => request<any>(`/team/positions/${id}/seats/${memberId}`, {method: "DELETE"}),
  authority: (companyId?: number | null) => request<any>(`/team/authority${cq(companyId)}`),
  createRule: (body: any) => request<any>(`/team/authority/rules`, {method: "POST", body: JSON.stringify(body)}),
  updateRule: (id: number, body: any) => request<any>(`/team/authority/rules/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  deleteRule: (id: number) => request<any>(`/team/authority/rules/${id}`, {method: "DELETE"}),
  seedDefaults: (body: any) => request<any>(`/team/authority/seed-defaults`, {method: "POST", body: JSON.stringify(body)}),
  evaluate: (body: any) => request<any>(`/team/authority/evaluate`, {method: "POST", body: JSON.stringify(body)}),
};

// M2c: vận hành công ty — quy trình (D4), KPI (D5), giao ban (D6), tuân thủ (D7), sẵn sàng agent (D8).
// M2e — công ty agent-native
export const apiNative = {
  rules: (companyId?: number | null) => request<any>(`/team/rules${cq(companyId)}`),
  createRule: (body: any) => request<any>(`/team/rules`, {method: "POST", body: JSON.stringify(body)}),
  updateRule: (id: number, body: any) => request<any>(`/team/rules/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  deleteRule: (id: number) => request<any>(`/team/rules/${id}`, {method: "DELETE"}),
  testRules: (body: any) => request<any>(`/team/rules/test`, {method: "POST", body: JSON.stringify(body)}),
  syncRules: () => request<any>(`/team/rules/sync`, {method: "POST"}),
  contracts: (companyId?: number | null) => request<any>(`/team/contracts${cq(companyId)}`),
  createContract: (body: any) => request<any>(`/team/contracts`, {method: "POST", body: JSON.stringify(body)}),
  updateContract: (id: number, body: any) => request<any>(`/team/contracts/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  archiveContract: (id: number) => request<any>(`/team/contracts/${id}`, {method: "DELETE"}),
  validateOutput: (id: number, output: string) => request<any>(`/team/contracts/${id}/validate`, {method: "POST", body: JSON.stringify({output})}),
  taskContract: (taskId: number) => request<any>(`/team/tasks/${taskId}/contract`),
  submitOutput: (taskId: number, output: any) => request<any>(`/team/tasks/${taskId}/output`, {method: "POST", body: JSON.stringify({output})}),
  coverage: (companyId?: number | null) => request<any>(`/team/coverage${cq(companyId)}`),
  saveSchedule: (memberId: number, body: any) => request<any>(`/team/seats/${memberId}/schedule`, {method: "PUT", body: JSON.stringify(body)}),
  addLeave: (memberId: number, body: any) => request<any>(`/team/seats/${memberId}/leaves`, {method: "POST", body: JSON.stringify(body)}),
  deleteLeave: (id: number) => request<any>(`/team/leaves/${id}`, {method: "DELETE"}),
  createSla: (body: any) => request<any>(`/team/sla-policies`, {method: "POST", body: JSON.stringify(body)}),
  updateSla: (id: number, body: any) => request<any>(`/team/sla-policies/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  deleteSla: (id: number) => request<any>(`/team/sla-policies/${id}`, {method: "DELETE"}),
  agentHr: (companyId?: number | null) => request<any>(`/team/agent-hr${cq(companyId)}`),
};

export const apiOps = {
  processes: (companyId?: number | null) => request<any>(`/team/processes${cq(companyId)}`),
  createProcess: (body: any) => request<any>(`/team/processes`, {method: "POST", body: JSON.stringify(body)}),
  updateProcess: (id: number, body: any) => request<any>(`/team/processes/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  archiveProcess: (id: number) => request<any>(`/team/processes/${id}`, {method: "DELETE"}),
  seedProcesses: (body: any) => request<any>(`/team/processes/seed`, {method: "POST", body: JSON.stringify(body)}),
  startProcess: (id: number, body: any) => request<any>(`/team/processes/${id}/start`, {method: "POST", body: JSON.stringify(body)}),
  instances: (id: number) => request<any>(`/team/processes/${id}/instances`),
  cancelInstance: (id: number) => request<any>(`/team/process-instances/${id}/cancel`, {method: "POST"}),
  createHoliday: (body: any) => request<any>(`/team/compliance/holidays`, {method: "POST", body: JSON.stringify(body)}),
  updateHoliday: (id: number, body: any) => request<any>(`/team/compliance/holidays/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  deleteHoliday: (id: number) => request<any>(`/team/compliance/holidays/${id}`, {method: "DELETE"}),
  stepOutcome: (runId: number, outcome: string) => request<any>(`/team/process-step-runs/${runId}/outcome`, {method: "POST", body: JSON.stringify({outcome})}),
  kpis: (companyId?: number | null) => request<any>(`/team/kpis${cq(companyId)}`),
  snapshotKpis: (body: any) => request<any>(`/team/kpis/snapshot`, {method: "POST", body: JSON.stringify(body)}),
  createKpi: (body: any) => request<any>(`/team/kpis`, {method: "POST", body: JSON.stringify(body)}),
  updateKpi: (id: number, body: any) => request<any>(`/team/kpis/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  deleteKpi: (id: number) => request<any>(`/team/kpis/${id}`, {method: "DELETE"}),
  recordKpi: (id: number, body: any) => request<any>(`/team/kpis/${id}/measurements`, {method: "POST", body: JSON.stringify(body)}),
  rhythm: (companyId?: number | null) => request<any>(`/team/rhythm${cq(companyId)}`),
  saveRhythm: (body: any) => request<any>(`/team/rhythm/config`, {method: "PUT", body: JSON.stringify(body)}),
  runRhythm: (body: any) => request<any>(`/team/rhythm/run`, {method: "POST", body: JSON.stringify(body)}),
  compliance: (companyId?: number | null) => request<any>(`/team/compliance${cq(companyId)}`),
  saveCompliance: (body: any) => request<any>(`/team/compliance/settings`, {method: "PUT", body: JSON.stringify(body)}),
  seedCompliance: (body: any) => request<any>(`/team/compliance/seed`, {method: "POST", body: JSON.stringify(body)}),
  generateCompliance: (companyId?: number | null) => request<any>(`/team/compliance/generate`, {method: "POST", body: JSON.stringify({company_id: companyId ?? null})}),
  createComplianceRule: (body: any) => request<any>(`/team/compliance/rules`, {method: "POST", body: JSON.stringify(body)}),
  updateComplianceRule: (id: number, body: any) => request<any>(`/team/compliance/rules/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  deleteComplianceRule: (id: number) => request<any>(`/team/compliance/rules/${id}`, {method: "DELETE"}),
  complianceDone: (id: number) => request<any>(`/team/compliance/deadlines/${id}/done`, {method: "POST"}),
  readiness: (companyId?: number | null) => request<any>(`/team/readiness${cq(companyId)}`),
  assessReadiness: (body: any) => request<any>(`/team/readiness`, {method: "POST", body: JSON.stringify(body)}),
  syncKpis: (companyId?: number | null) => request<any>(`/team/kpis/sync-positions`, {method: "POST", body: JSON.stringify({company_id: companyId ?? null})}),
};

// M3: Nhân sự AI — tuyển (wizard), sửa hồ sơ 2 chiều, lệch & đồng bộ lại, vòng đời, quyền tool theo seat.
// agentId ở đây là id của bảng agents (seat), không phải member id.
export const apiSharedMemory = {
  list: (p: {scope?: string; scope_id?: number | null; q?: string} = {}) => {
    const qs = new URLSearchParams();
    if (p.scope) qs.set("scope", p.scope);
    if (p.scope_id) qs.set("scope_id", String(p.scope_id));
    if (p.q) qs.set("q", p.q);
    return request<any>(`/shared-memory${qs.toString() ? `?${qs}` : ""}`);
  },
  options: () => request<any>(`/shared-memory/options`),
  create: (body: any) => request<any>(`/shared-memory`, {method: "POST", body: JSON.stringify(body)}),
  update: (id: number, body: any) => request<any>(`/shared-memory/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  forget: (id: number) => request<any>(`/shared-memory/${id}`, {method: "DELETE"}),
};

// M5b việc 9: kho tri thức hợp nhất + lỗ hổng + khoá học.
export const apiA2A = {
  external: () => request<any>(`/a2a/external`),
  addExternal: (body: {card_url?: string; endpoint_url?: string; name?: string; auth_header?: string}) =>
    request<any>(`/a2a/external`, {method: "POST", body: JSON.stringify(body)}),
  patchExternal: (id: number, body: {enabled?: boolean; auth_header?: string; name?: string}) =>
    request<any>(`/a2a/external/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  removeExternal: (id: number) => request<any>(`/a2a/external/${id}`, {method: "DELETE"}),
  send: (id: number, text: string, context_id?: string) =>
    request<any>(`/a2a/external/${id}/send`, {method: "POST", body: JSON.stringify({text, context_id})}),
  exposure: (agentId: number) => request<any>(`/a2a/expose/${agentId}`),
  expose: (agentId: number, body: {enabled: boolean; rotate?: boolean}) =>
    request<any>(`/a2a/expose/${agentId}`, {method: "POST", body: JSON.stringify(body)}),
};

export const apiLearning = {
  docs: () => request<any>(`/learning/docs`),
  addDoc: (body: any) => request<any>(`/learning/docs`, {method: "POST", body: JSON.stringify(body)}),
  upload: (file: File, scope: Record<string, any> = {}) => {
    const fd = new FormData(); fd.append("file", file);
    Object.entries(scope).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") fd.append(k, String(v)); });
    return request<any>(`/learning/docs/upload`, {method: "POST", body: fd});
  },
  resync: (id: number) => request<any>(`/learning/docs/${id}/resync`, {method: "POST"}),
  removeDoc: (id: number) => request<any>(`/learning/docs/${id}`, {method: "DELETE"}),
  patchDoc: (id: number, body: {title?: string; is_core?: boolean; role_keyword?: string}) =>
    request<any>(`/learning/docs/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  corePreview: (agentId: number) => request<any>(`/learning/core/${agentId}`),
  coreSync: () => request<any>(`/learning/core/sync`, {method: "POST"}),
  search: (q: string) => request<any>(`/learning/search?q=${encodeURIComponent(q)}`),
  gaps: (status = "open") => request<any>(`/learning/gaps?status=${status}`),
  resolveGap: (id: number, body: {document_id?: number | null; dismiss?: boolean}) =>
    request<any>(`/learning/gaps/${id}/resolve`, {method: "POST", body: JSON.stringify(body)}),
  courses: () => request<any>(`/learning/courses`),
  course: (id: number) => request<any>(`/learning/courses/${id}`),
  createCourse: (body: any) => request<any>(`/learning/courses`, {method: "POST", body: JSON.stringify(body)}),
  updateCourse: (id: number, body: any) => request<any>(`/learning/courses/${id}`, {method: "PUT", body: JSON.stringify(body)}),
  enroll: (id: number, body: {agent_ids?: number[]; department_ids?: number[]}) =>
    request<any>(`/learning/courses/${id}/enroll`, {method: "POST", body: JSON.stringify(body)}),
  genQuiz: (id: number, body: {author_agent_id?: number | null; questions?: number} = {}) =>
    request<any>(`/learning/courses/${id}/quiz/generate`, {method: "POST", body: JSON.stringify(body)}),
  step: (enrollmentId: number) => request<any>(`/learning/enrollments/${enrollmentId}/step`, {method: "POST"}),
  retake: (enrollmentId: number, from_start = false) =>
    request<any>(`/learning/enrollments/${enrollmentId}/retake`, {method: "POST", body: JSON.stringify({from_start})}),
  agent: (agentId: number) => request<any>(`/learning/agents/${agentId}`),
  suites: () => request<any>(`/learning/eval-suites`),
  suiteCreate: (body: any) => request<any>(`/learning/eval-suites`, {method: "POST", body: JSON.stringify(body)}),
  suiteUpdate: (id: number, body: any) => request<any>(`/learning/eval-suites/${id}`, {method: "PUT", body: JSON.stringify(body)}),
  career: (agentId: number, days = 30) => request<any>(`/learning/career/${agentId}?days=${days}`),
  careerEval: (agentId: number, suite_id: number) => request<any>(`/learning/career/${agentId}/eval`, {method: "POST", body: JSON.stringify({suite_id})}),
  careerLevel: (agentId: number, level: string, reason: string) =>
    request<any>(`/learning/career/${agentId}/level`, {method: "POST", body: JSON.stringify({level, reason})}),
  evalRun: (id: number) => request<any>(`/learning/eval-runs/${id}`),
  skills: () => request<any>(`/learning/skills`),
  skill: (id: number) => request<any>(`/learning/skills/${id}`),
  skillGovernance: () => request<any>(`/learning/skills/governance`),
  skillEnforce: () => request<any>(`/learning/skills/governance`, {method: "POST"}),
  skillSync: () => request<any>(`/learning/skills/sync`, {method: "POST"}),
  skillCreate: (body: any) => request<any>(`/learning/skills`, {method: "POST", body: JSON.stringify(body)}),
  versionUpdate: (id: number, body: any) => request<any>(`/learning/skill-versions/${id}`, {method: "PUT", body: JSON.stringify(body)}),
  versionEval: (id: number, agent_id: number) => request<any>(`/learning/skill-versions/${id}/eval`, {method: "POST", body: JSON.stringify({agent_id})}),
  versionSubmit: (id: number) => request<any>(`/learning/skill-versions/${id}/submit`, {method: "POST"}),
  skillInstall: (id: number, agent_ids: number[], version_id?: number) =>
    request<any>(`/learning/skills/${id}/install`, {method: "POST", body: JSON.stringify({agent_ids, version_id})}),
  skillRollback: (id: number, version_id: number) =>
    request<any>(`/learning/skills/${id}/rollback`, {method: "POST", body: JSON.stringify({version_id})}),
};

export const apiAgentsHR = {
  roster: (companyId?: number | null) => request<any>(`/agents/roster${companyId ? `?company_id=${companyId}` : ""}`),
  options: () => request<any>(`/agents/hire/options`),
  hire: (body: any) => request<any>(`/agents/hire`, {method: "POST", body: JSON.stringify(body)}),
  update: (agentId: number, body: any) => request<any>(`/agents/${agentId}/hr`, {method: "PATCH", body: JSON.stringify(body)}),
  drift: (agentId: number) => request<any>(`/agents/${agentId}/drift`),
  resync: (agentId: number, body: {direction: "push" | "pull"; files?: string[]; fields?: string[]}) =>
    request<any>(`/agents/${agentId}/resync`, {method: "POST", body: JSON.stringify(body)}),
  provision: (agentId: number) => request<any>(`/agents/${agentId}/provision`, {method: "POST"}),
  provisionAll: (body: {dry_run?: boolean; allow_restart?: boolean} = {}) =>
    request<any>(`/agents/provision-all`, {method: "POST", body: JSON.stringify(body)}),
  wireGateway: (body: {dry_run?: boolean; allow_restart?: boolean} = {}) =>
    request<any>(`/agents/gateway/wire`, {method: "POST", body: JSON.stringify(body)}),
  modelTiers: () => request<any>(`/agents/model-tiers`),
  lifecycle: (agentId: number, body: {action: "pause" | "resume" | "retire"; reassign_to_member_id?: number | null;
    remove_from_gateway?: boolean; reason?: string}) =>
    request<any>(`/agents/${agentId}/lifecycle`, {method: "POST", body: JSON.stringify(body)}),
  tools: (agentId: number) => request<any>(`/agents/${agentId}/tools`),
  limits: (agentId: number) => request<any>(`/agents/${agentId}/limits`),
  memory: (agentId: number) => request<any>(`/agents/${agentId}/memory`),
  lessons: (agentId: number) => request<any>(`/agents/${agentId}/lessons`),
  lessonsExtract: (agentId: number) => request<any>(`/agents/${agentId}/lessons/extract`, {method: "POST"}),
  memoryChange: (agentId: number, body: any) =>
    request<any>(`/agents/${agentId}/memory`, {method: "POST", body: JSON.stringify(body)}),
  versions: (agentId: number) => request<any>(`/agents/${agentId}/versions`),
  restore: (agentId: number, version: number) =>
    request<any>(`/agents/${agentId}/versions/${version}/restore`, {method: "POST"}),
  personaCheck: (agentId: number) => request<any>(`/agents/${agentId}/persona-check`, {method: "POST"}),
};

// M4a — Công việc & lượt chạy (/api/work): danh sách, bảng, side-peek, review chéo, chạy ngay.
export const apiWork = {
  meta: () => request<any>(`/work/meta`),
  list: (params: Record<string, string | number | undefined | null> = {}) => {
    const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
    return request<any>(`/work/tasks${q ? `?${q}` : ""}`);
  },
  get: (id: number) => request<any>(`/work/tasks/${id}`),
  create: (body: any) => request<any>(`/work/tasks`, {method: "POST", body: JSON.stringify(body)}),
  update: (id: number, body: any) => request<any>(`/work/tasks/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  move: (id: number, status: string, expected_revision?: string) =>
    request<any>(`/work/tasks/${id}/move`, {method: "POST", body: JSON.stringify({status, expected_revision})}),
  reviewers: (id: number, reviewer_member_ids: number[]) =>
    request<any>(`/work/tasks/${id}/reviewers`, {method: "PUT", body: JSON.stringify({reviewer_member_ids})}),
  decide: (id: number, decision: "approve" | "revise", note = "") =>
    request<any>(`/work/tasks/${id}/review`, {method: "POST", body: JSON.stringify({decision, note})}),
  run: (id: number) => request<any>(`/work/tasks/${id}/run`, {method: "POST"}),
};

// M4b — Hộp việc & phê duyệt một chạm (/api/inbox), Chi phí & ngân sách 3 nấc (/api/costs).
const qs = (params: Record<string, string | number | undefined | null>) => {
  const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
  return q ? `?${q}` : "";
};
export const apiInboxHub = {
  items: (params: Record<string, string | number | undefined | null> = {}) => request<any>(`/inbox/items${qs(params)}`),
  summary: () => request<any>(`/inbox/summary`),
  setStatus: (id: number, status: "unread" | "read" | "done") =>
    request<any>(`/inbox/items/${id}/status`, {method: "POST", body: JSON.stringify({status})}),
  readAll: () => request<any>(`/inbox/items/read-all`, {method: "POST"}),
  decide: (id: number, body: {decision: "approve" | "reject"; note?: string; expected_revision?: number;
    grant_scope?: "task" | "seat" | "department"; edited_text?: string}) =>
    request<any>(`/inbox/approvals/${id}/decide`, {method: "POST", body: JSON.stringify(body)}),
  approval: (id: number) => request<any>(`/inbox/approvals/${id}`),
  item: (id: number) => request<any>(`/inbox/items/${id}`),
  escalate: () => request<any>(`/inbox/escalate`, {method: "POST"}),
};
export const apiCosts = {
  overview: (days = 30) => request<any>(`/costs/overview?days=${days}`),
  budgets: () => request<any>(`/costs/budgets`),
  budget: (id: number) => request<any>(`/costs/budgets/${id}`),
  create: (body: any) => request<any>(`/costs/budgets`, {method: "POST", body: JSON.stringify(body)}),
  update: (id: number, body: any) => request<any>(`/costs/budgets/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  override: (id: number, body: {reason: string; add_usd?: number; amount_limit?: number}) =>
    request<any>(`/costs/budgets/${id}/override`, {method: "POST", body: JSON.stringify(body)}),
  archive: (id: number) => request<any>(`/costs/budgets/${id}`, {method: "DELETE"}),
};

/* R1 vai trò theo công ty + R2 cho thuê agent (seat_leases) */
export const apiRental = {
  myCompanies: () => request<any>(`/team/my-companies`),
  companyAccess: (companyId: number) => request<any>(`/team/company-access?company_id=${companyId}`),
  setCompanyAccess: (body: any) => request<any>(`/team/company-access`, {method: "PUT", body: JSON.stringify(body)}),
  removeCompanyAccess: (id: number) => request<any>(`/team/company-access/${id}`, {method: "DELETE"}),
  linkSeat: (body: any) => request<any>(`/team/user-seats`, {method: "POST", body: JSON.stringify(body)}),
  // R2 cho thuê agent
  leases: (side: "provider" | "renter", companyId?: number | null) =>
    request<any>(`/leases?side=${side}${companyId ? `&company_id=${companyId}` : ""}`),
  lease: (id: number) => request<any>(`/leases/${id}`),
  leasePolicy: (id: number) => request<any>(`/leases/${id}/policy`),
  createOffer: (body: any) => request<any>(`/leases`, {method: "POST", body: JSON.stringify(body)}),
  previewOffer: (code: string) => request<any>(`/leases/offer/${encodeURIComponent(code)}`),
  acceptOffer: (body: any) => request<any>(`/leases/accept`, {method: "POST", body: JSON.stringify(body)}),
  updateLease: (id: number, body: any) => request<any>(`/leases/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  leaseStatus: (id: number, action: "suspend" | "resume", reason = "") =>
    request<any>(`/leases/${id}/status`, {method: "POST", body: JSON.stringify({action, reason})}),
  endLease: (id: number, reason = "") => request<any>(`/leases/${id}/end`, {method: "POST", body: JSON.stringify({reason})}),
  requestChange: (id: number, body: {changes: any; note?: string}) =>
    request<any>(`/leases/${id}/change-requests`, {method: "POST", body: JSON.stringify(body)}),
  decideChange: (id: number, crId: number, decision: "approved" | "rejected") =>
    request<any>(`/leases/${id}/change-requests/${crId}/decide`, {method: "POST", body: JSON.stringify({decision})}),
};

// M3 — thư viện tài liệu & tri thức công ty (/api/team/docs…)
const dq = (o: Record<string, any>) => qs(o).slice(1);
export const apiDocs = {
  list: (companyId: number | null, f: Record<string, any> = {}) => request<any>(`/team/docs?${dq({company_id: companyId, ...f})}`),
  get: (id: number) => request<any>(`/team/docs/${id}`),
  create: (body: any) => request<any>(`/team/docs`, {method: "POST", body: JSON.stringify(body)}),
  patch: (id: number, body: any) => request<any>(`/team/docs/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  upload: (file: File, fields: Record<string, any>) => {
    const fd = new FormData(); fd.append("file", file);
    Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") fd.append(k, String(v)); });
    return request<any>(`/team/docs/upload`, {method: "POST", body: fd});
  },
  newVersion: (id: number, body: any) => request<any>(`/team/docs/${id}/versions`, {method: "POST", body: JSON.stringify(body)}),
  editVersion: (id: number, vid: number, body: any) => request<any>(`/team/docs/${id}/versions/${vid}`, {method: "PATCH", body: JSON.stringify(body)}),
  submit: (id: number, vid: number) => request<any>(`/team/docs/${id}/versions/${vid}/submit`, {method: "POST"}),
  decide: (id: number, vid: number, decision: "approved" | "rejected", note = "", override_conflicts = false) =>
    request<any>(`/team/docs/${id}/versions/${vid}/decide`, {method: "POST", body: JSON.stringify({decision, note, override_conflicts})}),
  flagStatus: (id: number, flagId: number, status: "resolved" | "dismissed") =>
    request<any>(`/team/docs/${id}/flags/${flagId}`, {method: "POST", body: JSON.stringify({status})}),
  chunks: (id: number) => request<any>(`/team/docs/${id}/chunks`),
  facts: (companyId: number | null) => request<any>(`/team/facts?${dq({company_id: companyId})}`),
  putFact: (body: any) => request<any>(`/team/facts`, {method: "PUT", body: JSON.stringify(body)}),
  delFact: (id: number) => request<any>(`/team/facts/${id}`, {method: "DELETE"}),
  // M3d hồ sơ bắt buộc & lưu trữ
  requirements: (companyId: number | null) => request<any>(`/team/doc-requirements?${dq({company_id: companyId})}`),
  addRequirement: (body: any) => request<any>(`/team/doc-requirements`, {method: "POST", body: JSON.stringify(body)}),
  editRequirement: (id: number, body: any) => request<any>(`/team/doc-requirements/${id}`, {method: "PATCH", body: JSON.stringify(body)}),
  attachRequirement: (id: number, documentId: number) =>
    request<any>(`/team/doc-requirements/${id}/attach`, {method: "POST", body: JSON.stringify({document_id: documentId})}),
  dispose: (id: number, reason = "") => request<any>(`/team/docs/${id}/dispose`, {method: "POST", body: JSON.stringify({reason})}),
  diff: (id: number, a?: number, b?: number) => request<any>(`/team/docs/${id}/diff?${dq({a, b})}`),
  review: (id: number, note = "") => request<any>(`/team/docs/${id}/review`, {method: "POST", body: JSON.stringify({note})}),
  archive: (id: number, reason = "") => request<any>(`/team/docs/${id}/archive`, {method: "POST", body: JSON.stringify({reason})}),
  importSops: (companyId: number) => request<any>(`/team/docs/import-sops?company_id=${companyId}`, {method: "POST"}),
  file: async (fileId: number, filename: string) => {
    const token = typeof window !== "undefined" ? localStorage.getItem("clawcompany_token") : null;
    const r = await fetch(`${API_BASE}/team/docs/files/${fileId}`, {headers: token ? {Authorization: `Bearer ${token}`} : {}});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
  },
};
