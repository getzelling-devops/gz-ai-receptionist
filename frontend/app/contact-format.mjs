// Display only. Original provider transcripts remain unchanged in the CRM.
export function formatTranscriptPhones(text) {
  return text.replace(/(?<![\w@$(])\(?\+?\d(?:[ \t().-]*\d){9,16}\)?(?![ \t().-]*\d|[\w@])/g, raw => {
    if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw;
    let digits=raw.replace(/\D/g,"");
    if(digits.length===11&&digits.startsWith("1"))digits=digits.slice(1);
    if(!/^[2-9]\d{2}[2-9]\d{6}$/.test(digits))return raw;
    return digits.slice(0,3)+"-"+digits.slice(3,6)+"-"+digits.slice(6);
  });
}
