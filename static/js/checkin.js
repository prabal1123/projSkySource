document.addEventListener("DOMContentLoaded", function () {

    // ==================================================
    // CHECK IN — location required (blocking)
    // ==================================================

    var checkInForm = document.getElementById("checkInForm");

    if (checkInForm) {
        var checkInButton = document.getElementById("checkInButton");
        var checkInLatField = document.getElementById("checkInLatitude");
        var checkInLngField = document.getElementById("checkInLongitude");
        var checkInErrorEl = document.getElementById("checkInLocationError");

        checkInForm.addEventListener("submit", function (event) {
            // If coordinates are already filled in, let it submit normally.
            if (checkInLatField.value && checkInLngField.value) {
                return;
            }

            event.preventDefault();

            if (!navigator.geolocation) {
                checkInErrorEl.style.display = "block";
                return;
            }

            checkInButton.disabled = true;
            checkInButton.textContent = "Getting location...";

            navigator.geolocation.getCurrentPosition(
                function (position) {
                    checkInLatField.value = position.coords.latitude;
                    checkInLngField.value = position.coords.longitude;
                    checkInErrorEl.style.display = "none";
                    checkInButton.textContent = "Check In →";
                    checkInButton.disabled = false;
                    checkInForm.submit();
                },
                function (error) {
                    checkInErrorEl.style.display = "block";
                    checkInButton.textContent = "Check In →";
                    checkInButton.disabled = false;
                },
                { enableHighAccuracy: true, timeout: 10000 }
            );
        });
    }


    // ==================================================
    // CHECK OUT — location optional (never blocks)
    // ==================================================

    var checkOutForm = document.getElementById("checkOutForm");

    if (checkOutForm) {
        var checkOutButton = document.getElementById("checkOutButton");
        var checkOutLatField = document.getElementById("checkOutLatitude");
        var checkOutLngField = document.getElementById("checkOutLongitude");
        var checkOutSubmitted = false;

        checkOutForm.addEventListener("submit", function (event) {
            // Once the location attempt is done (success or fail), let it submit normally.
            if (checkOutSubmitted) {
                return;
            }

            event.preventDefault();

            if (!navigator.geolocation) {
                checkOutSubmitted = true;
                checkOutForm.submit();
                return;
            }

            checkOutButton.disabled = true;
            checkOutButton.textContent = "Checking out...";

            navigator.geolocation.getCurrentPosition(
                function (position) {
                    checkOutLatField.value = position.coords.latitude;
                    checkOutLngField.value = position.coords.longitude;
                    checkOutSubmitted = true;
                    checkOutForm.submit();
                },
                function (error) {
                    // Denied or failed — submit anyway, without location.
                    checkOutSubmitted = true;
                    checkOutForm.submit();
                },
                { enableHighAccuracy: true, timeout: 5000 }
            );
        });
    }

});