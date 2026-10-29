// scene_marine.js — la scène du bandeau de l'équipage, dessinée de toutes pièces (29/10/2026).
// Le fondateur : « le bateau… que niveau motion design, animation, image, ce soit créé de toutes pièces, magnifique ».
// Un crépuscule en mer : ciel, étoiles, soleil et son reflet, nuages, trois houles en parallaxe, un trois-mâts qui tangue,
// des mouettes. Du SVG construit ici (aucun fichier, aucune image) ; les mouvements sont en CSS (equipage.css), coupés
// quand l'appareil demande moins d'animations.

const NS = "http://www.w3.org/2000/svg";
function n(tag, attrs = {}, ...enfants) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  enfants.forEach((x) => e.append(x));
  return e;
}
function degrade(id, arrets, vertical = true) {
  const g = n("linearGradient", { id, x1: "0", y1: "0", x2: vertical ? "0" : "1", y2: vertical ? "1" : "0" });
  arrets.forEach(([o, c, a]) => g.append(n("stop", { offset: o, "stop-color": c, "stop-opacity": a ?? 1 })));
  return g;
}
//  Une houle : un motif de 1200 répété deux fois (la boucle glisse d'une période, sans couture).
function houle(y, amplitude, periode, couleur, classe) {
  let d = `M0 ${y}`;
  for (let x = 0; x < 2400; x += periode) {
    d += ` q${periode / 4} ${-amplitude} ${periode / 2} 0 t${periode / 2} 0`;
  }
  d += " V400 H0 Z";
  return n("path", { d, fill: couleur, class: "sm-houle " + classe });
}

export function sceneMarine() {
  const u = "sm" + Math.random().toString(36).slice(2, 7);   // des identifiants propres à cette scène
  const svg = n("svg", { class: "scene-marine", viewBox: "0 0 1200 400", preserveAspectRatio: "xMidYMax slice", "aria-hidden": "true" });
  const defs = n("defs", {},
    degrade(u + "c", [["0", "#150c26"], [".42", "#4a1f3d"], [".72", "#b4483a"], [".9", "#ec8a42"], ["1", "#f6c46a"]]),
    degrade(u + "m", [["0", "#2a4a5c"], [".5", "#143142"], ["1", "#071821"]]),
    degrade(u + "v", [["0", "#f7e7c3"], ["1", "#d9b98a"]], false),
    n("radialGradient", { id: u + "s" }, n("stop", { offset: "0", "stop-color": "#fff6d8" }), n("stop", { offset: ".55", "stop-color": "#ffd27a" }),
      n("stop", { offset: "1", "stop-color": "#f39a3f", "stop-opacity": "0" })),
    n("filter", { id: u + "f", x: "-50%", y: "-50%", width: "200%", height: "200%" }, n("feGaussianBlur", { stdDeviation: "18" })));
  svg.append(defs, n("rect", { width: "1200", height: "400", fill: `url(#${u}c)` }));
  //  Les étoiles (haut du ciel)
  const etoiles = n("g", { class: "sm-etoiles" });
  let graine = 7;
  const hasard = () => ((graine = (graine * 9301 + 49297) % 233280) / 233280);
  for (let i = 0; i < 46; i++) {
    etoiles.append(n("circle", { cx: (hasard() * 1200).toFixed(1), cy: (hasard() * 150).toFixed(1), r: (0.6 + hasard() * 1.3).toFixed(2),
      fill: "#fff3dc", class: "sm-etoile", style: `animation-delay:${(hasard() * 4).toFixed(2)}s` }));
  }
  svg.append(etoiles);
  //  Le soleil, son halo qui respire
  svg.append(n("g", { class: "sm-soleil" },
    n("circle", { cx: "835", cy: "262", r: "150", fill: `url(#${u}s)`, opacity: ".55", class: "sm-halo" }),
    n("circle", { cx: "835", cy: "262", r: "62", fill: "#ffe2a0" }),
    n("circle", { cx: "835", cy: "262", r: "62", fill: `url(#${u}s)` })));
  //  Les nuages qui dérivent
  const nuage = (x, y, k, classe) => n("g", { class: "sm-nuage " + classe, transform: `translate(${x} ${y}) scale(${k})` },
    n("path", { d: "M0 30 q10-26 40-20 q14-22 44-12 q22-14 46 4 q30 0 32 22 q-8 10-30 10 H10 q-14 0-10-4z", fill: "#f7c9a4", opacity: ".32" }));
  svg.append(nuage(120, 70, 1.4, "lent"), nuage(560, 40, 1, "moyen"), nuage(960, 95, 1.2, "lent2"));
  //  La mer, le reflet du soleil qui scintille
  svg.append(n("rect", { y: "262", width: "1200", height: "138", fill: `url(#${u}m)` }));
  const reflet = n("g", { class: "sm-reflet" });
  [[272, 120], [284, 96], [296, 132], [309, 80], [322, 110], [336, 70], [351, 92], [367, 54]].forEach(([y, l], i) =>
    reflet.append(n("rect", { x: 835 - l / 2, y, width: l, height: "3.2", rx: "1.6", fill: "#ffd98c", opacity: (0.75 - i * 0.07).toFixed(2),
      style: `animation-delay:${(i * 0.35).toFixed(2)}s` })));
  svg.append(reflet);
  svg.append(n("g", { class: "sm-loin" }, houle(270, 3, 120, "#1d3b4d", "h1")));
  //  Le trois-mâts : il tangue (rotation autour de sa quille) et danse sur la houle
  const coque = "M-150 -6 L150 -6 Q140 30 104 40 L-108 40 Q-140 28 -150 -6 Z";
  //  Une voile carrée de galion, gonflée par le vent (le ventre plus clair), sous sa vergue.
  const voile = (x, haut, bas, w) => n("g", {},
    n("path", { d: `M${x - w} ${haut} Q${x} ${haut + 7} ${x + w} ${haut} L${x + w * 0.9} ${bas} Q${x} ${bas + 13} ${x - w * 0.9} ${bas} Z`,
      fill: `url(#${u}v)`, stroke: "#8a6f45", "stroke-width": "1.1" }),
    n("path", { d: `M${x - w * 0.55} ${haut + 6} Q${x} ${(haut + bas) / 2 + 6} ${x - w * 0.5} ${bas + 4}`, stroke: "#c9a06a", "stroke-width": "1",
      fill: "none", opacity: ".7" }),
    n("path", { d: `M${x - w - 3} ${haut} H${x + w + 3}`, stroke: "#2b1d12", "stroke-width": "3", "stroke-linecap": "round" }));
  const navire = n("g", { class: "sm-navire" },
    n("g", { class: "sm-roulis" },
      //  le gréement
      n("path", { d: "M-112 -6 L-70 -150 M-112 -6 L0 -190 M150 -6 L64 -160 M0 -190 L64 -160 M-70 -150 L0 -190 M0 -190 L150 -6",
        stroke: "#2b1d12", "stroke-width": "1.1", fill: "none", opacity: ".8" }),
      //  les mâts
      n("path", { d: "M-70 -6 V-150 M0 -6 V-190 M64 -6 V-160", stroke: "#2b1d12", "stroke-width": "4.5", "stroke-linecap": "round" }),
      voile(-70, -146, -110, 25), voile(-70, -104, -64, 32),
      voile(0, -186, -146, 30), voile(0, -140, -96, 38), voile(0, -90, -40, 45),
      voile(64, -156, -120, 23), voile(64, -114, -76, 30),
      n("path", { d: "M150 -6 L220 -40 L150 -16 Z", fill: `url(#${u}v)`, stroke: "#8a6f45", "stroke-width": "1" }),
      //  le pavillon du clan
      n("path", { d: "M0 -190 L0 -214 L30 -207 L0 -200", fill: "#8e2a24", class: "sm-pavillon" }),
      //  la coque, le liseré de laiton, les sabords
      n("path", { d: coque, fill: "#2a160b" }),
      n("path", { d: "M-146 4 H146", stroke: "#c9a35a", "stroke-width": "2.4" }),
      ...[-100, -60, -20, 20, 60, 100].map((x) => n("rect", { x: x - 6, y: "12", width: "12", height: "8", rx: "2", fill: "#f1b45a", opacity: ".9" })),
      n("path", { d: "M-150 -6 L-176 -24", stroke: "#2b1d12", "stroke-width": "4", "stroke-linecap": "round" })));
  const ancre = n("g", { transform: "translate(470 300) scale(.62)" }, navire);
  svg.append(ancre);
  svg.append(houle(300, 6, 160, "#163243", "h2"), houle(330, 9, 220, "#0f2533", "h3"), houle(362, 12, 300, "#09192300", "h4"));
  svg.lastChild.setAttribute("fill", "#081620");
  //  Les mouettes
  const mouettes = n("g", { class: "sm-mouettes" });
  [[640, 120, 1], [680, 104, .8], [730, 132, .9]].forEach(([x, y, k], i) => mouettes.append(
    n("g", { transform: `translate(${x} ${y}) scale(${k})` }, n("path", { d: "M-12 0 Q-6 -7 0 0 Q6 -7 12 0", stroke: "#1a0f08", "stroke-width": "2.2",
      fill: "none", "stroke-linecap": "round", class: "sm-aile", style: `animation-delay:${i * 0.25}s` }))));
  svg.append(mouettes);
  return svg;
}
