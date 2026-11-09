// ---------- Raccourcis ----------
const $ = (s) => document.querySelector(s);
let urlCourante = "", format = "mp4", qualite = "best";

const montrer = (el, oui = true) => $(el).classList.toggle("cache", !oui);
const erreur = (msg) => { $("#erreur").textContent = msg; montrer("#erreur"); };

function formaterDuree(s) {
  if (!s) return "durée inconnue";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(sec).padStart(2, "0");
}

// ---------- Étape 1 : analyser le lien (POST /api/info) ----------
async function analyser() {
  const url = $("#url").value.trim();
  if (!url) return erreur("Colle d'abord un lien.");
  montrer("#erreur", false); montrer("#resultat", false); montrer("#chargement");
  $("#btn-analyser").disabled = true;
  try {
    const rep = await fetch("/api/info", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
    });
    const data = await rep.json();
    if (!rep.ok) throw new Error(data.detail || "Erreur inconnue.");
    if (data.trop_longue) throw new Error("Cette vidéo est trop longue.");
    urlCourante = url;
    $("#miniature").src = data.miniature || "";
    $("#titre").textContent = data.titre;
    $("#meta").textContent = `${data.plateforme} • ${formaterDuree(data.duree)}`;
    // On grise les qualités supérieures à ce que la vidéo propose
    document.querySelectorAll("#qualites .chip").forEach((b) => {
      b.disabled = !!(data.hauteur_max && b.dataset.q !== "best" && +b.dataset.q > data.hauteur_max);
    });
    montrer("#resultat");
  } catch (e) {
    erreur(e.message);
  } finally {
    montrer("#chargement", false); $("#btn-analyser").disabled = false;
  }
}

// ---------- Choix du format / de la qualité ----------
function activer(groupe, bouton) {
  document.querySelectorAll(`${groupe} .chip`).forEach((b) => b.classList.remove("actif"));
  bouton.classList.add("actif");
}
$("#formats").addEventListener("click", (e) => {
  const b = e.target.closest(".chip"); if (!b) return;
  activer("#formats", b); format = b.dataset.format;
  montrer("#qualites", format === "mp4");  // pas de qualité pour le MP3
});
$("#qualites").addEventListener("click", (e) => {
  const b = e.target.closest(".chip"); if (!b || b.disabled) return;
  activer("#qualites", b); qualite = b.dataset.q;
});

// ---------- Étape 2 : télécharger (GET /api/download) avec progression ----------
async function telecharger() {
  montrer("#erreur", false); montrer("#progression");
  const barre = $("#barre-dl");
  barre.className = "barre-int indeterminee"; barre.style.width = "";
  $("#etat-dl").textContent = "Préparation du fichier sur le serveur…";
  $("#btn-dl").disabled = true;
  try {
    const params = new URLSearchParams({ url: urlCourante, format, quality: qualite });
    const rep = await fetch("/api/download?" + params);
    if (!rep.ok) {
      const d = await rep.json().catch(() => ({}));
      throw new Error(d.detail || "Erreur pendant le téléchargement.");
    }
    // Le serveur a fini : on lit le fichier en suivant la progression
    const total = +rep.headers.get("Content-Length") || 0;
    const lecteur = rep.body.getReader(), morceaux = [];
    let recu = 0;
    barre.className = "barre-int"; barre.style.width = "0%";
    $("#etat-dl").textContent = "Téléchargement…";
    for (;;) {
      const { done, value } = await lecteur.read();
      if (done) break;
      morceaux.push(value); recu += value.length;
      if (total) barre.style.width = Math.round((recu / total) * 100) + "%";
    }
    // Nom du fichier envoyé par le serveur
    const cd = rep.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*=utf-8''([^;]+)/i) || cd.match(/filename="([^"]+)"/i);
    const nom = m ? decodeURIComponent(m[1]) : "video." + format;
    // On déclenche l'enregistrement sur l'appareil
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(morceaux));
    a.download = nom; document.body.appendChild(a); a.click(); a.remove();
    $("#etat-dl").textContent = "✅ Terminé !";
  } catch (e) {
    montrer("#progression", false); erreur(e.message);
  } finally {
    $("#btn-dl").disabled = false;
  }
}

$("#btn-analyser").addEventListener("click", analyser);
$("#url").addEventListener("keydown", (e) => { if (e.key === "Enter") analyser(); });
$("#btn-dl").addEventListener("click", telecharger);
