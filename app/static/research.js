const $=id=>document.getElementById(id);let session=null,page=0,limit=50,items=[],facetsLoaded=false;const compareSelection=new Map();
const SUPABASE_URL="https://zgfdvhzhvccsfmpoaqah.supabase.co";
const SUPABASE_PUBLISHABLE_KEY="sb_publishable_qShRk3J_yqTiyTzVcwYNYw_4ppeaFf8";

const authClient=window.supabase.createClient(SUPABASE_URL,SUPABASE_PUBLISHABLE_KEY,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
function headers(){return session?.access_token?{"Authorization":"Bearer "+session.access_token}:{}}
async function api(path,options={}){const r=await fetch(path,{...options,headers:{...headers(),...(options.headers||{})}});const d=await r.json().catch(()=>({detail:r.statusText}));if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:JSON.stringify(d.detail||"Request failed"));return d}
function pct(v){return v==null?"—":(Number(v)*100).toFixed(2)+"%"}
function num(v){return v==null?"—":Number(v).toFixed(2)}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function note(msg,error=false){$("notice").textContent=msg;$("notice").classList.toggle("error",error)}
function activate(tab){document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));["screener","profile","compare","watchlist","overlap"].forEach(id=>$(id).classList.toggle("hidden",id!==tab));if(tab==="watchlist")loadWatchlist().catch(e=>note(e.message,true));if(tab==="compare")syncCompareInput()}
document.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>activate(b.dataset.tab));
let loadedAuthUserId=null,authBusy=false,passwordRecoveryMode=false;
function authValues(){const email=$("authEmail").value.trim(),password=$("authPassword").value;const at=email.indexOf("@");if(!email||email.includes(" ")||at<1||email.lastIndexOf(".")<=at+1)throw new Error("Enter a valid email address.");if(!password||password.length<8)throw new Error("Password must contain at least 8 characters.");return {email,password}}
function setAuthBusy(busy,mode=""){authBusy=busy;["signIn","signUp","resetPassword"].forEach(id=>$(id).disabled=busy);$("signIn").textContent=busy&&mode==="signin"?"Signing in…":"Sign in";$("signUp").textContent=busy&&mode==="signup"?"Creating…":"Create account";$("resetPassword").textContent=busy&&mode==="reset"?"Sending…":"Forgot password?"}
async function updateAuthState(nextSession){session=nextSession;const signedIn=!!session?.access_token,userId=signedIn?session.user.id:null;$("authEmail").hidden=signedIn;$("authPassword").hidden=signedIn;$("signIn").hidden=signedIn;$("signUp").hidden=signedIn;$("resetPassword").hidden=signedIn;$("signOut").hidden=!signedIn||passwordRecoveryMode;$("researchRecoveryPanel").classList.toggle("hidden",!passwordRecoveryMode);$("authStatus").textContent=signedIn?"Signed in as "+(session.user.email||"your account")+".":"Sign in to access the research workspace.";if(signedIn&&!passwordRecoveryMode&&loadedAuthUserId!==userId){loadedAuthUserId=userId;try{await Promise.all([loadFacets(),loadWatchlist()]);note("Preparing verified fund rankings from stored NAV history…");await loadScreen();await loadCategoryLeaderboards();note("Signed in. Global and category-wise fund rankings loaded.")}catch(e){if(session?.user?.id===userId)loadedAuthUserId=null;note(e.message,true)}}else if(!signedIn){loadedAuthUserId=null;items=[];compareSelection.clear();updateCompareSelectionUI();$("fundRows").innerHTML='<tr><td colspan="17" class="muted">Sign in to load fund research.</td></tr>';$("watchlistRows").innerHTML='<tr><td colspan="7" class="muted">Sign in to load your saved funds.</td></tr>'}}
$("researchAuthForm").addEventListener("submit",async event=>{event.preventDefault();if(authBusy)return;try{const {email,password}=authValues();setAuthBusy(true,"signin");note("Verifying your account…");const {data,error}=await authClient.auth.signInWithPassword({email,password});if(error)throw error;await updateAuthState(data.session)}catch(e){note(e.message||"Sign-in failed. Please try again.",true)}finally{setAuthBusy(false)}});
$("signUp").onclick=async()=>{if(authBusy)return;try{const {email,password}=authValues();setAuthBusy(true,"signup");note("Creating your account…");const {data,error}=await authClient.auth.signUp({email,password,options:{emailRedirectTo:new URL("/",window.location.origin).toString()}});if(error)throw error;if(data.session){await updateAuthState(data.session);note("Account created and signed in.")}else note("Account request received. Check your inbox and spam folder for the confirmation link, then return to sign in.")}catch(e){note(e.message||"Account creation failed. Please try again.",true)}finally{setAuthBusy(false)}};
$("resetPassword").onclick=async()=>{if(authBusy)return;try{const email=$("authEmail").value.trim(),at=email.indexOf("@");if(!email||email.includes(" ")||at<1||email.lastIndexOf(".")<=at+1)throw new Error("Enter a valid account email first.");setAuthBusy(true,"reset");const {error}=await authClient.auth.resetPasswordForEmail(email,{redirectTo:new URL("/research",window.location.origin).toString()});if(error)throw error;note("If an account exists for that email, a password-reset link will be sent. Check your inbox and spam folder.")}catch(e){note(e.message||"Could not start password reset.",true)}finally{setAuthBusy(false)}};
$("signOut").onclick=async()=>{try{const {error}=await authClient.auth.signOut();if(error)throw error;passwordRecoveryMode=false;await updateAuthState(null)}catch(e){note(e.message||"Sign-out failed.",true)}};
authClient.auth.onAuthStateChange((event,nextSession)=>{if(event==="PASSWORD_RECOVERY"){passwordRecoveryMode=true;note("Choose a new password to finish account recovery.")}queueMicrotask(()=>updateAuthState(nextSession).catch(e=>note(e.message||"Could not load your workspace.",true)))});
$("saveNewPassword").onclick=async()=>{if(authBusy)return;try{const password=$("newPassword").value;if(!password||password.length<8)throw new Error("New password must contain at least 8 characters.");authBusy=true;$("saveNewPassword").disabled=true;$("saveNewPassword").textContent="Updating…";const {error}=await authClient.auth.updateUser({password});if(error)throw error;passwordRecoveryMode=false;$("newPassword").value="";const {data}=await authClient.auth.getSession();await updateAuthState(data.session);note("Password updated successfully.")}catch(e){note(e.message||"Could not update your password.",true)}finally{authBusy=false;$("saveNewPassword").disabled=false;$("saveNewPassword").textContent="Update password"}};
function setFacetOptions(id,values,label){const element=$(id),current=element.value;element.innerHTML='<option value="">All '+esc(label)+'</option>'+(values||[]).map(value=>'<option value="'+esc(value)+'">'+esc(value)+'</option>').join("");if((values||[]).includes(current))element.value=current}
function renderCategoryQuickFilters(facets){
  const root=$("categoryQuickFilters");if(!root)return;
  const groups=Array.isArray(facets?.categories)?facets.categories:[];
  const subs=Array.isArray(facets?.sub_categories)?facets.sub_categories:[];
  const groupButtons=groups.map(value=>'<button type="button" data-quick-kind="group" data-quick-value="'+esc(value)+'" aria-pressed="false">'+esc(value.replace(/ Scheme$/,""))+'</button>').join("");
  const subButtons=subs.map(value=>'<button type="button" data-quick-kind="sub" data-quick-value="'+esc(value)+'" aria-pressed="false">'+esc(value)+'</button>').join("");
  root.innerHTML='<span class="quick-label">Asset groups</span><div class="quick-group-list"><button type="button" data-quick-kind="all" class="active" aria-pressed="true">All categories</button>'+groupButtons+'</div>'+(subButtons?'<details class="quick-subcategories"><summary>Browse sub-categories <span>'+subs.length+' available</span></summary><div class="quick-subcategory-list">'+subButtons+'</div></details>':"");
  root.querySelectorAll("[data-quick-kind]").forEach(button=>button.addEventListener("click",()=>{
    const kind=button.dataset.quickKind,value=button.dataset.quickValue||"";
    if(kind==="all"){$("category").value="";$("subCategory").value=""}
    else if(kind==="group"){$("category").value=value;$("subCategory").value=""}
    else {$("category").value="";$("subCategory").value=value}
    page=0;syncCategoryQuickFilters();loadScreen().catch(error=>note(error.message,true));
  }));
  syncCategoryQuickFilters();
}
function syncCategoryQuickFilters(){
  const root=$("categoryQuickFilters");if(!root)return;
  const group=$("category")?.value||"",sub=$("subCategory")?.value||"";
  root.querySelectorAll("[data-quick-kind]").forEach(button=>{
    const kind=button.dataset.quickKind,value=button.dataset.quickValue||"";
    const active=kind==="all"?!group&&!sub:kind==="group"?!!group&&group===value:!!sub&&sub===value;button.classList.toggle("active",active);button.setAttribute("aria-pressed",String(active));
  });
}
async function loadFacets(){if(!session?.access_token)return null;const d=await api("/v1/nav/facets");setFacetOptions("category",d.categories,"scheme groups");setFacetOptions("subCategory",d.sub_categories,"sub-categories");setFacetOptions("assetClass",d.asset_classes,"asset classes");setFacetOptions("plan",d.plan_types,"plans");setFacetOptions("option",d.option_types,"options");renderCategoryQuickFilters(d);facetsLoaded=true;return d}
async function loadScreen(){if(!session?.access_token)throw new Error("Please sign in first.");const p=new URLSearchParams({limit:String(limit),offset:String(page*limit),days:$("days").value,sort_by:$("sortBy").value,sort_order:$("sortOrder").value,min_observations:$("minObservations").value});if($("q").value.trim())p.set("q",$("q").value.trim());if($("category").value)p.set("category_group",$("category").value);if($("subCategory").value)p.set("sub_category",$("subCategory").value);if($("assetClass").value)p.set("asset_class",$("assetClass").value);if($("plan").value)p.set("plan_type",$("plan").value);if($("option").value)p.set("option_type",$("option").value);const d=await api("/v1/analytics/screener?"+p.toString());items=d.items||[];syncCategoryQuickFilters();renderRows();$("pageInfo").textContent=(d.total_matching?("Showing global ranks "+(page*limit+1)+"–"+(page*limit+items.length)+" of "+d.total_matching):"No matching funds");$("prev").disabled=page===0;$("next").disabled=(page+1)*limit>=d.total_matching;$("screenerFreshness").textContent="Research snapshot refreshed "+new Date(d.refreshed_at).toLocaleString()+" · "+d.total_matching+" matching schemes · "+d.days_requested+"-day window · Global ranking by "+d.sort_by.replaceAll("_"," ");return d}
function renderRows(){
  const qualityLabel=x=>{
    const details=(x.quality_flags||[]).map(flag=>[
      flag.type,
      flag.nav_date||"",
      flag.affected_periods?.length?"periods: "+flag.affected_periods.join(", "):"",
      flag.ratio?"NAV ratio: "+Number(flag.ratio).toFixed(3):""
    ].filter(Boolean).join(" · ")).join("; ");
    if(x.data_quality_status==="REVIEW_REQUIRED")return '<span class="muted" title="'+esc(details)+'"> · Data review</span>';
    if(x.data_quality_status==="ADJUSTED"){
      const sources=(x.nav_adjustments_applied||[]).map(event=>event.source_note||event.action).join("; ");
      return '<span class="muted" title="'+esc(sources)+'"> · NAV adjusted</span>';
    }
    return "";
  };
  const riskLabel=x=>x.risk_statistics_status==="MIXED_FREQUENCY_NOT_COMPARABLE"
    ? '<span class="muted" title="Daily risk statistics are suppressed because this history mixes monthly and daily NAV observations."> · Risk stats unavailable</span>'
    : "";
  $("fundRows").innerHTML=items.map(x=>{
    const quality=qualityLabel(x),risk=riskLabel(x);
    return '<tr data-code="'+x.scheme_code+'"><td><span class="rankbadge">#'+x.rank+'</span></td><td class="categoryrank">'+(x.category_rank==null?"—":"#"+x.category_rank)+'</td><td><div class="fund">'+esc(x.scheme_name)+'</div><div class="subfund">Code '+x.scheme_code+' · '+esc(x.category_group||"Group unavailable")+(x.category?' · '+esc(x.category):"")+' · '+esc(x.plan_type||"Plan unavailable")+' · '+esc(x.option_type||"Option unavailable")+quality+risk+'</div></td><td>₹'+(x.latest_nav?num(x.latest_nav):"—")+'<div class="subfund">'+esc(x.nav_date||"No NAV")+'</div></td><td class="'+(x.return_1m>=0?"positive":"negative")+'">'+pct(x.return_1m)+'</td><td class="'+(x.return_3m>=0?"positive":"negative")+'">'+pct(x.return_3m)+'</td><td class="'+(x.return_6m>=0?"positive":"negative")+'">'+pct(x.return_6m)+'</td><td class="'+(x.return_1y>=0?"positive":"negative")+'">'+pct(x.return_1y)+'</td><td class="'+(x.return_3y>=0?"positive":"negative")+'">'+pct(x.return_3y)+'</td><td class="'+(x.return_5y>=0?"positive":"negative")+'">'+pct(x.return_5y)+'</td><td>'+pct(x.cagr)+'</td><td>'+pct(x.volatility)+'</td><td>'+num(x.sharpe_ratio)+'</td><td class="negative">'+pct(x.max_drawdown)+'</td><td>'+pct(x.positive_month_rate)+'</td><td>'+pct(x.rolling_1y_positive_rate)+'</td><td><div class="row-actions"><button type="button" class="view-fund" data-watch-code="'+x.scheme_code+'">+ Watch</button><button type="button" class="compare-fund-btn '+(compareSelection.has(String(x.scheme_code))?"selected":"")+'" data-compare-code="'+x.scheme_code+'" aria-pressed="'+String(compareSelection.has(String(x.scheme_code)))+'">'+(compareSelection.has(String(x.scheme_code))?"Selected":"Compare")+'</button></div></td></tr>';
  }).join("")||'<tr><td colspan="17" class="muted">No funds match the selected filters or no verified NAV research snapshot is available.</td></tr>';
  document.querySelectorAll("#fundRows tr[data-code]").forEach(tr=>tr.onclick=()=>{activate("profile");$("profileCode").value=tr.dataset.code;loadProfile().catch(e=>note(e.message,true))});
  document.querySelectorAll("[data-watch-code]").forEach(btn=>btn.onclick=async event=>{event.stopPropagation();try{await addToWatchlist(Number(btn.dataset.watchCode))}catch(e){note(e.message,true)}});
  document.querySelectorAll("[data-compare-code]").forEach(btn=>btn.onclick=event=>{event.stopPropagation();toggleCompareFund(btn.dataset.compareCode,items.find(x=>String(x.scheme_code)===btn.dataset.compareCode)?.scheme_name||("Scheme "+btn.dataset.compareCode))});
  updateCompareSelectionUI();
}

function toggleCompareFund(code,name){
  const key=String(code);
  if(compareSelection.has(key))compareSelection.delete(key);
  else {if(compareSelection.size>=10){note("You can compare up to 10 funds at a time.",true);return}compareSelection.set(key,name)}
  updateCompareSelectionUI();renderRows();
}
function updateCompareSelectionUI(){
  const bar=$("compareSelectionBar");if(!bar)return;
  const count=compareSelection.size;
  bar.classList.toggle("hidden",count===0);
  $("compareSelectionTitle").textContent=count+" fund"+(count===1?"":"s")+" selected";
  $("compareSelectionNames").textContent=[...compareSelection.values()].join(" · ")||"Select 2–10 funds to compare.";
  $("openCompareSelection").disabled=count<2;
}
function syncCompareInput(){
  if($("compareCodesResearch")&&compareSelection.size>=2)$("compareCodesResearch").value=[...compareSelection.keys()].join(", ");
}
$("clearCompareSelection").onclick=()=>{compareSelection.clear();updateCompareSelectionUI();renderRows();};
$("openCompareSelection").onclick=()=>{syncCompareInput();activate("compare");};
$("loadSelectedCompare").onclick=()=>{if(compareSelection.size<2){note("Select at least two funds in the screener first.",true);return}syncCompareInput();};
function renderComparisonResult(data){
  const results=data.results||[];
  const columns=[["Total NAV return","total_return","pct"],["CAGR","cagr","pct"],["Annualised volatility","annualized_volatility","pct"],["Maximum drawdown","max_drawdown","pct"],["Sharpe ratio","sharpe_ratio","num"],["Sortino ratio","sortino_ratio","num"]];
  const cells=results.map(item=>{
    const m=item.metrics||{},ok=m.status==="OK";
    return '<article class="compare-result-card"><div class="compare-card-head"><div><strong>'+esc(item.scheme_name)+'</strong><small>AMFI '+esc(item.scheme_code)+'</small></div><span class="tag">'+(ok?"Metrics available":"Insufficient history")+'</span></div><div class="compare-card-nav"><strong>'+(item.latest_nav==null?"—":"₹"+num(item.latest_nav))+'</strong><small>NAV as of '+esc(item.latest_nav_date||"unavailable")+' · '+esc(item.observations)+' observations</small></div><div class="compare-metrics">'+columns.map(([label,key,format])=>'<div><span>'+label+'</span><strong>'+(ok?(format==="pct"?pct(m[key]):num(m[key])):"—")+'</strong></div>').join("")+'</div></article>';
  }).join("");
  $("compareResearchResult").innerHTML='<div class="compare-result-grid">'+cells+'</div><div class="compare-methodology">'+esc(data.methodology||"Each fund is calculated from stored NAV observations.")+' · '+esc(data.days_requested)+' days · Risk-free assumption '+pct(data.risk_free_rate_assumption)+'</div>';
}
async function runFundComparison(){
  const codes=$("compareCodesResearch").value.split(",").map(value=>value.trim()).filter(Boolean);
  if(codes.length<2||codes.length>10||codes.some(value=>!/^\d+$/.test(value)))throw new Error("Enter 2–10 valid numeric AMFI scheme codes separated by commas.");
  const numeric=codes.map(Number);
  if(new Set(numeric).size!==numeric.length)throw new Error("Remove duplicate scheme codes before comparing.");
  const button=$("runFundComparison");button.disabled=true;button.textContent="Comparing…";
  $("compareResearchResult").innerHTML='<div class="compare-empty">Calculating each fund from stored NAV history…</div>';
  try{const data=await api("/v1/analytics/compare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({scheme_codes:numeric,days:Number($("compareDaysResearch").value)})});renderComparisonResult(data);note("Fund comparison completed from stored AMFI NAV observations.")}
  finally{button.disabled=false;button.textContent="Compare funds"}
}
$("runFundComparison").onclick=()=>runFundComparison().catch(error=>{$("compareResearchResult").innerHTML='<div class="notice error">'+esc(error.message)+'</div>';note(error.message,true)});

$("runScreen").onclick=()=>{page=0;loadScreen().catch(e=>note(e.message,true))};$("prev").onclick=()=>{if(page>0){page--;loadScreen().catch(e=>note(e.message,true))}};$("next").onclick=()=>{page++;loadScreen().catch(e=>note(e.message,true))};
$("loadProfile").onclick=()=>loadProfile().catch(e=>note(e.message,true));

const LEADER_GROUPS=["Equity Scheme","Debt Scheme","Hybrid Scheme","Life Cycle Funds","Other Schemes"];
function populateLeaderboardMonths(){
  const select=$("leaderboardMonth");if(select.options.length)return;
  const now=new Date();const base=new Date(now.getFullYear(),now.getMonth(),1);
  for(let offset=1;offset<=12;offset++){const d=new Date(base.getFullYear(),base.getMonth()-offset,1);const value=d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");const label=d.toLocaleDateString(undefined,{month:"long",year:"numeric"});select.add(new Option(label,value));}
}
function rankMovement(value){
  if(value==null)return '<span class="rankmove">—</span>';
  if(value>0)return '<span class="rankmove up">▲ '+value+'</span>';
  if(value<0)return '<span class="rankmove down">▼ '+Math.abs(value)+'</span>';
  return '<span class="rankmove">— 0</span>';
}
function renderLeaderboardCard(group,data){
  const renderFunds=rows=>(rows||[]).map((x,i)=>'<div class="leaderfund"><strong><span class="categoryrank">#'+(x.category_rank||i+1)+'</span> '+esc(x.scheme_name)+'</strong><small>'+esc(x.option_type||"")+'</small><div><span class="leaderreturn">'+pct(x.monthly_return)+'</span>'+rankMovement(x.rank_change)+'</div><div class="leaderfund-actions">'+(x.scheme_code?'<button type="button" data-leader-code="'+x.scheme_code+'">Research profile</button>':"")+'</div></div>').join("");
  const categories=data?.categories||[];
  if(categories.length){
    return categories.map(category=>{
      const contents=renderFunds(category.items);
      return '<article class="leadercard"><h3>'+esc(category.category)+'</h3><div class="groupmeta">'+esc(group)+' · '+esc(category.count)+' eligible funds · '+esc(data?.plan_type||"Direct")+' '+esc(data?.option_type||"Growth")+'</div>'+(contents||'<div class="leader-empty">No verified monthly return is available for this sub-category.</div>')+'</article>';
    }).join("");
  }
  const contents=renderFunds(data?.items||[]);
  return '<article class="leadercard"><h3>'+esc(group)+'</h3><div class="groupmeta">'+esc(data?.count??0)+' eligible funds · '+esc(data?.plan_type||"Direct")+' '+esc(data?.option_type||"Growth")+'</div>'+(contents||'<div class="leader-empty">No verified monthly return is available for this month and plan.</div>')+'</article>';
}
async function loadCategoryLeaderboards(){
  if(!session?.access_token)return null;
  populateLeaderboardMonths();
  const month=$("leaderboardMonth").value,plan=$("leaderboardPlan").value,option=$("leaderboardOption").value;
  $("leaderboardCards").innerHTML=LEADER_GROUPS.map(group=>'<article class="leadercard"><div class="leader-empty">Loading '+esc(group)+'…</div></article>').join("");
  const results=await Promise.all(LEADER_GROUPS.map(async group=>{
    try{const p=new URLSearchParams({month,category_group:group,plan_type:plan,option_type:option,limit:"3"});return {group,data:await api("/v1/analytics/monthly-leaderboard?"+p.toString())}}
    catch(error){return {group,error}}
  }));
  $("leaderboardCards").innerHTML=results.map(x=>renderLeaderboardCard(x.group,x.data)).join("");
  document.querySelectorAll("[data-leader-code]").forEach(button=>button.onclick=()=>{
    activate("profile");$("profileCode").value=button.dataset.leaderCode;
    loadProfile().catch(error=>note(error.message,true));
  });
  const first=results.find(x=>x.data)?.data;
  const errors=results.filter(x=>x.error);
  const subcategoryCount=results.reduce((total,item)=>total+(item.data?.category_count||0),0);
  $("leaderboardFreshness").textContent=first
    ? "Completed month: "+new Date(month+"-02T00:00:00").toLocaleDateString(undefined,{month:"long",year:"numeric"})+" · "+subcategoryCount+" subcategories ranked · Previous comparison: "+first.previous_month+" · Snapshot refreshed "+new Date(first.refreshed_at).toLocaleString()+(errors.length?" · "+errors.length+" category request(s) unavailable":"")
    : "Monthly leaderboard data is not yet available. A fresh 365-day research snapshot with monthly return history is required.";
  return results;
}
$("refreshLeaderboards").onclick=()=>loadCategoryLeaderboards().catch(e=>note(e.message,true));
$("leaderboardMonth").onchange=()=>loadCategoryLeaderboards().catch(e=>note(e.message,true));
$("leaderboardPlan").onchange=()=>loadCategoryLeaderboards().catch(e=>note(e.message,true));
$("leaderboardOption").onchange=()=>loadCategoryLeaderboards().catch(e=>note(e.message,true));

async function loadWatchlist(){if(!session?.access_token)return null;const requestedUserId=session.user.id;const d=await api("/v1/watchlist");if(!session?.access_token||session.user.id!==requestedUserId)return null;renderWatchlist(d.items||[]);return d}
function renderWatchlist(rows){$("watchlistRows").innerHTML=rows.map(x=>'<tr><td style="text-align:left"><div class="fund">'+esc(x.scheme_name)+'</div><div class="subfund">Scheme '+esc(x.scheme_code)+'</div></td><td>'+esc(x.plan_type||"—")+'</td><td>'+esc(x.option_type||"—")+'</td><td>₹'+(x.latest_nav?num(x.latest_nav):"—")+'</td><td>'+esc(x.nav_date||"—")+'</td><td>'+esc((x.added_at||"").slice(0,10))+'</td><td><button type="button" class="view-fund" data-remove-watch-code="'+x.scheme_code+'">Remove</button></td></tr>').join("")||'<tr><td colspan="7" class="muted">Your watchlist is empty. Add funds from the screener or a fund profile.</td></tr>';document.querySelectorAll("[data-remove-watch-code]").forEach(btn=>btn.onclick=async()=>{try{await removeFromWatchlist(Number(btn.dataset.removeWatchCode))}catch(e){note(e.message,true)}})}
async function addToWatchlist(code){await api("/v1/watchlist",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({scheme_code:code})});await loadWatchlist();note("Fund added to your private watchlist.")}
async function removeFromWatchlist(code){await api("/v1/watchlist/"+code,{method:"DELETE"});await loadWatchlist();note("Fund removed from your private watchlist.")}
$("refreshWatchlist").onclick=()=>loadWatchlist().catch(e=>note(e.message,true));
function overlapPct(value){return value==null?"—":Number(value).toFixed(2)+"%"}
async function runHoldingsOverlap(){const a=Number($("overlapSchemeA").value),b=Number($("overlapSchemeB").value);if(!Number.isInteger(a)||a<=0||!Number.isInteger(b)||b<=0)throw new Error("Enter two valid AMFI scheme codes.");if(a===b)throw new Error("Choose two different schemes.");$("overlapBody").innerHTML='<div class="panel">Calculating ISIN-level overlap from the latest imported disclosures…</div>';const params=new URLSearchParams({scheme_a:String(a),scheme_b:String(b)});const d=await api("/v1/analytics/holdings-overlap?"+params.toString());const stale=d.status==="STALE_DISCLOSURE";const top=(d.top_shared_holdings||[]).map(item=>'<tr><td style="text-align:left">'+esc(item.security_name)+'</td><td>'+esc(item.isin)+'</td><td>'+overlapPct(item.weight_in_scheme_a_pct)+'</td><td>'+overlapPct(item.weight_in_scheme_b_pct)+'</td><td>'+overlapPct(item.matched_overlap_weight_pct)+'</td></tr>').join("")||'<tr><td colspan="5" class="muted">No common valid ISIN holdings found.</td></tr>';const card=(name,x)=>'<div class="stat"><label>'+name+'</label><strong>'+esc(x.scheme_name)+'</strong><div class="muted">As of '+esc(x.as_of_date)+' · '+esc(x.disclosure_age_days)+' days old</div><div class="muted">ISIN coverage '+overlapPct(x.coverage.isin_coverage_pct)+'</div></div>';$("overlapBody").innerHTML='<div class="notice '+(stale?"error":"")+'">'+(stale?"Warning: at least one holdings disclosure is more than 90 days old.":"Both disclosures are within the 90-day freshness window.")+'</div><div class="stats">'+card("Scheme A",d.scheme_a)+card("Scheme B",d.scheme_b)+'<div class="stat"><label>Matched ISIN overlap</label><strong>'+overlapPct(d.holdings_overlap_pct)+'</strong><div class="muted">'+d.common_isin_count+' common securities</div></div><div class="stat"><label>Shared weight in A / B</label><strong>'+overlapPct(d.shared_weight_in_scheme_a_pct)+' / '+overlapPct(d.shared_weight_in_scheme_b_pct)+'</strong></div></div><div class="panel"><h3>Top shared holdings</h3><div class="tablewrap"><table style="min-width:700px"><thead><tr><th>Security</th><th>ISIN</th><th>Weight A</th><th>Weight B</th><th>Matched overlap</th></tr></thead><tbody>'+top+'</tbody></table></div></div><p class="footnote">'+esc(d.methodology)+' '+(d.limitations||[]).map(esc).join(" ")+'</p>';note("Holdings overlap calculated from source-dated disclosures.") }
$("runOverlap").onclick=()=>runHoldingsOverlap().catch(e=>{note(e.message,true);$("overlapBody").innerHTML='<div class="notice error">'+esc(e.message)+'</div>'});
async function loadProfile(){
 const code=$("profileCode").value.trim();
 if(!/^\d+$/.test(code))throw new Error("Enter a valid numeric scheme code.");
 if(typeof window.renderFundDetail!=="function")throw new Error("The fund detail renderer is not available. Reload the page and retry.");
 $("profileBody").innerHTML='<div class="panel">Loading fund profile, stored NAV history, benchmark alignment and source evidence…</div>';
 try{return await window.renderFundDetail(code,$("profileDays").value)}
 catch(error){$("profileBody").innerHTML='<div class="notice error">Fund profile could not be loaded: '+esc(error.message||"Unknown error")+'</div>';throw error}
}
authClient.auth.getSession().then(({data,error})=>{if(error)throw error;return updateAuthState(data.session)}).catch(e=>note(e.message||"Could not restore your session. Please sign in again.",true));
