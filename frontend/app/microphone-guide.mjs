export function microphoneBrowser(ua = "", touchPoints = 0) {
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && touchPoints > 1);
  if (ios && /CriOS/.test(ua)) return "ios-chrome";
  if (ios && /Safari/.test(ua) && !/FxiOS|EdgiOS|GSA\//.test(ua)) return "ios-safari";
  if (/Android/.test(ua) && /Chrome/.test(ua) && !/SamsungBrowser|EdgA|OPR/.test(ua)) return "android-chrome";
  return "other";
}

export const microphoneGuides = {
  "ios-safari": {
    label: "Safari · iPhone / iPad",
    en: ["Tap Safari’s page menu beside the address, then Website Settings (or More → Website Settings).", "Set Microphone to Ask or Allow. If needed, check iPhone Settings → Apps → Safari → Microphone.", "Return here and tap Agree and call. Choose Allow when Safari asks."],
    es: ["Abra el menú de página junto a la dirección en Safari y entre en Ajustes del sitio web (o Más → Ajustes del sitio web).", "En Micrófono, elija Preguntar o Permitir. Si hace falta, revise Ajustes del iPhone → Apps → Safari → Micrófono.", "Vuelva y pulse Acepto, iniciar llamada. Elija Permitir cuando Safari lo solicite."],
    url: "https://support.apple.com/guide/iphone/iphb01fc3c85/ios",
  },
  "ios-chrome": {
    label: "Chrome · iPhone / iPad",
    en: ["In iPhone Settings → Privacy & Security → Microphone, allow Chrome. You may also find this under Settings → Apps → Chrome.", "Return to Chrome and reload this page. If Chrome shows a microphone control beside the address, allow access for this site.", "Tap Agree and call, then choose Allow when Chrome asks."],
    es: ["En Ajustes del iPhone → Privacidad y seguridad → Micrófono, permita Chrome. También puede aparecer en Ajustes → Apps → Chrome.", "Vuelva a Chrome y recargue esta página. Si aparece un control de micrófono junto a la dirección, permita el acceso para este sitio.", "Pulse Acepto, iniciar llamada y elija Permitir cuando Chrome lo solicite."],
    url: "https://support.google.com/chrome/answer/2693767?co=GENIE.Platform%3DiOS",
  },
  "android-chrome": {
    label: "Chrome · Android",
    en: ["Open Chrome’s menu → Settings → Site settings → Microphone.", "Allow sites to ask. If this site is blocked, select it and choose Allow. Also allow Chrome’s microphone permission in Android Settings → Apps → Chrome → Permissions.", "Return here and tap Agree and call. Choose Allow when asked."],
    es: ["Abra el menú de Chrome → Configuración → Configuración de sitios → Micrófono.", "Permita que los sitios lo soliciten. Si este sitio está bloqueado, selecciónelo y elija Permitir. Revise también Ajustes de Android → Apps → Chrome → Permisos.", "Vuelva y pulse Acepto, iniciar llamada. Elija Permitir cuando se le pregunte."],
    url: "https://support.google.com/chrome/answer/2693767?co=GENIE.Platform%3DAndroid",
  },
  other: {
    label: "Other browser / Otro navegador",
    en: ["Open the browser’s site-permission menu beside the address and allow Microphone for this site.", "If the browser still cannot ask, check your device’s app permissions for that browser. In an app’s built-in browser, use its menu to open this page in Safari or Chrome.", "Return here and tap Agree and call. You can always continue typing or call (786) 977-2774."],
    es: ["Abra los permisos del sitio junto a la dirección y permita el Micrófono para este sitio.", "Si el navegador no puede solicitarlo, revise sus permisos en los ajustes del dispositivo. Si está dentro de otra app, use su menú para abrir la página en Safari o Chrome.", "Vuelva y pulse Acepto, iniciar llamada. También puede seguir escribiendo o llamar al (786) 977-2774."],
  },
};
