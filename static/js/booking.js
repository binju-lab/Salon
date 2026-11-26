(function () {
    "use strict";

    var form = document.getElementById("booking-form");
    if (!form) {
        return;
    }

    var slotsUrl = form.dataset.slotsUrl;
    var serviceId = form.dataset.serviceId;
    var stylistId = form.dataset.stylistId;
    var dateInput = document.getElementById("booking-date");
    var statusEl = document.getElementById("slot-status");
    var listEl = document.getElementById("slot-list");
    var startInput = document.getElementById("booking-start");
    var submitButton = document.getElementById("booking-submit");

    // Wording for every empty_reason the contract allows.
    var EMPTY_REASONS = {
        NO_SHIFT: "The stylist does not work on that day.",
        ALL_TAKEN: "Every remaining time on that day is already taken.",
        NO_WORKSTATION: "No suitable chair is free on that day.",
        NOT_QUALIFIED: "This stylist cannot perform that service."
    };

    function setStatus(text) {
        statusEl.textContent = text;
    }

    function resetSelection() {
        listEl.textContent = "";
        startInput.value = "";
        submitButton.disabled = true;
    }

    function selectSlot(button) {
        var buttons = listEl.querySelectorAll("button[data-start]");
        Array.prototype.forEach.call(buttons, function (candidate) {
            candidate.setAttribute("aria-pressed", candidate === button ? "true" : "false");
        });
        startInput.value = button.dataset.start;
        submitButton.disabled = false;
    }

    function renderSlots(slots) {
        slots.forEach(function (start) {
            var button = document.createElement("button");
            button.type = "button";
            button.className = "slot";
            button.dataset.start = start;
            button.setAttribute("aria-pressed", "false");
            button.textContent = start;
            button.addEventListener("click", function () {
                selectSlot(button);
            });
            listEl.appendChild(button);
        });
    }

    function readJson(response) {
        return response.json().catch(function () {
            return null;
        }).then(function (payload) {
            return { status: response.status, payload: payload };
        });
    }

    function loadSlots() {
        var day = dateInput.value;
        if (!day) {
            return;
        }

        resetSelection();
        setStatus("Loading times\u2026");

        var url = slotsUrl +
            "?service_id=" + encodeURIComponent(serviceId) +
            "&stylist_id=" + encodeURIComponent(stylistId) +
            "&date=" + encodeURIComponent(day);

        fetch(url, { headers: { Accept: "application/json" } })
            .then(readJson)
            .then(function (result) {
                var payload = result.payload || {};

                if (result.status === 401) {
                    window.location.assign(payload.login_url || "/auth/login");
                    return;
                }

                if (result.status !== 200) {
                    setStatus(payload.message || "Could not load times (" + result.status + ").");
                    return;
                }

                var slots = payload.slots || [];
                renderSlots(slots);

                if (slots.length > 0) {
                    setStatus(slots.length === 1 ? "1 time available." : slots.length + " times available.");
                    return;
                }

                // A missing reason still means "nothing bookable", so fall back to it.
                setStatus(EMPTY_REASONS[payload.empty_reason] || EMPTY_REASONS.ALL_TAKEN);
            })
            .catch(function () {
                // No automatic retry: a repeat could hide a real outage.
                setStatus("Could not reach the server. Check your connection and try again.");
            });
    }

    dateInput.addEventListener("change", loadSlots);
    loadSlots();
}());
