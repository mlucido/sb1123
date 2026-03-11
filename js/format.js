// Format helpers — shared across deal cards, tables, popups, exports
export function fmtDollar(n){ var neg=n<0; n=Math.abs(Math.round(n)); return (neg?'-':'')+'$'+n.toLocaleString(); }
export function fmtShort(n){ var neg=n<0; var a=Math.abs(n); var s=a>=1000000?'$'+(a/1000000).toFixed(2).replace(/0+$/,'').replace(/\.$/,'')+'M':a>=1000?'$'+Math.round(a/1000)+'K':'$'+Math.round(a); return neg?'-'+s:s; }
export function commas(n){ return n!=null?Math.round(n).toLocaleString():'—'; }
