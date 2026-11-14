export async function fetchJson(url:string, init:RequestInit={}, timeoutMs=14000):Promise<unknown> {
  const controller=new AbortController();
  let timedOut=false;
  const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);
  try {
    const res=await fetch(url,{...init,signal:controller.signal,headers:{'User-Agent':'CardScout-portfolio/0.1 (read-only market research)',...init.headers}});
    if(!res.ok)throw new Error(`上游服务 HTTP ${res.status}${res.status===429?'，请求过于频繁':''}`);
    return await res.json();
  } catch(error) {
    if(timedOut) throw new Error(`上游服务响应超时（${Math.round(timeoutMs/1000)} 秒），请稍后重试`);
    throw error;
  } finally {clearTimeout(timer);}
}
export const safeError=(e:unknown)=>{
  const message=e instanceof Error?e.message:String(e);
  return message==='fetch failed'?'无法连接 Steam 或上游数据服务，请检查服务端网络':message;
};
