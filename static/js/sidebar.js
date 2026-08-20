document.addEventListener("DOMContentLoaded", function () {

    const toggleButton = document.getElementById("sidebarToggle");
    const overlay = document.getElementById("sidebarOverlay");
    const sidebar = document.getElementById("hrSidebar");


    if (!sidebar) {
        return;
    }


    function openSidebar() {
        document.body.classList.add("sidebar-open");
    }


    function closeSidebar() {
        document.body.classList.remove("sidebar-open");
    }


    if (toggleButton) {

        toggleButton.addEventListener("click", function () {

            if (document.body.classList.contains("sidebar-open")) {
                closeSidebar();
            } else {
                openSidebar();
            }

        });

    }


    if (overlay) {

        overlay.addEventListener("click", function () {
            closeSidebar();
        });

    }


    document.addEventListener("keydown", function (event) {

        if (event.key === "Escape") {
            closeSidebar();
        }

    });


    sidebar.querySelectorAll("a").forEach(function (link) {

        link.addEventListener("click", function () {

            if (window.innerWidth < 992) {
                closeSidebar();
            }

        });

    });


    window.addEventListener("resize", function () {

        if (window.innerWidth >= 992) {
            closeSidebar();
        }

    });

});