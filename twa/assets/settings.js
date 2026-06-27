/* Bio-Quant TWA — bio-traits editor. POSTs to the guarded /api/v1/calibration. */
BioAuth.applyTheme();
BioAuth.requireContextOrGate();
var tg = BioAuth.tg;

function readForm() {
    function num(id) {
        var v = parseFloat(document.getElementById(id).value);
        return isNaN(v) ? null : v;
    }
    return {
        age: num("age"),
        weight_kg: num("weight"),
        height_cm: num("height")
    };
}

async function save() {
    var status = document.getElementById("status");
    status.innerText = "Saving…";
    try {
        var res = await apiFetch("/api/v1/calibration", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(readForm())
        });
        var data = await res.json();
        status.innerText = data.message || "Saved";
        if (tg) { try { tg.HapticFeedback.notificationOccurred("success"); } catch (e) {} }
    } catch (e) {
        status.innerText = "Save failed — check your connection.";
    }
}

document.getElementById("save-btn").addEventListener("click", save);

if (tg && tg.MainButton) {
    tg.MainButton.setText("Save Bio-Traits");
    tg.MainButton.show();
    tg.MainButton.onClick(save);
}
