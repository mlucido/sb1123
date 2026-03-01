// Format helpers — shared across deal cards, tables, popups, exports
export function fmtDollar(n){ return '$'+Math.round(n).toLocaleString(); }
export function fmtShort(n){ return n>=1000000?'$'+(n/1000000).toFixed(2).replace(/0+$/,'').replace(/\.$/,'')+'M':n>=1000?'$'+Math.round(n/1000)+'k':'$'+Math.round(n); }
export function commas(n){ return n!=null?Math.round(n).toLocaleString():'—'; }
