/** English release. Original DOM translation hooks remain compatible. */
window.i18n = (() => {
  const apply = () => {
    document.documentElement.lang = 'en';
    document.querySelectorAll('.lang-short').forEach(el => el.textContent = 'EN');
  };
  return {init:apply, apply, set:()=>{apply();return 'en'}, cycle:()=> 'en', current:'en', langs:['en'], t:{}};
})();
