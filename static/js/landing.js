document.addEventListener("DOMContentLoaded", () => {

    /* ==============================================
       NAVBAR SCROLL EFFECT
    ============================================== */

    const header = document.querySelector(".site-header");

    window.addEventListener("scroll", () => {
        if (window.scrollY > 20) {
            header?.classList.add("scrolled");
        } else {
            header?.classList.remove("scrolled");
        }
    });


    /* ==============================================
       SCROLL REVEAL
    ============================================== */

    const revealElements = document.querySelectorAll(
        ".platform-card, " +
        ".workflow-card, " +
        ".lifecycle-box, " +
        ".benefit-grid article, " +
        ".section-intro, " +
        ".workflow-copy, " +
        ".why-heading"
    );

    revealElements.forEach((element) => {
        element.classList.add("reveal");
    });

    const revealObserver = new IntersectionObserver(
        (entries) => {

            entries.forEach((entry) => {

                if (entry.isIntersecting) {

                    entry.target.classList.add(
                        "reveal-visible"
                    );

                    revealObserver.unobserve(
                        entry.target
                    );
                }

            });

        },
        {
            threshold: 0.12,
        }
    );

    revealElements.forEach((element) => {
        revealObserver.observe(element);
    });


    /* ==============================================
       HERO LOAD ANIMATION
    ============================================== */

    const heroCopy = document.querySelector(
        ".hero-copy"
    );

    const dashboard = document.querySelector(
        ".dashboard-window"
    );

    setTimeout(() => {
        heroCopy?.classList.add("hero-visible");
    }, 100);

    setTimeout(() => {
        dashboard?.classList.add(
            "dashboard-visible"
        );
    }, 300);


    /* ==============================================
       DASHBOARD PROGRESS ANIMATION
    ============================================== */

    const progressFill = document.querySelector(
        ".progress-fill"
    );

    const leaveBars = document.querySelectorAll(
        ".leave-track span"
    );

    const dashboardObserver = new IntersectionObserver(
        (entries) => {

            entries.forEach((entry) => {

                if (!entry.isIntersecting) {
                    return;
                }

                if (progressFill) {
                    progressFill.classList.add(
                        "animate-progress"
                    );
                }

                leaveBars.forEach((bar) => {

                    const finalWidth =
                        bar.style.width;

                    bar.style.setProperty(
                        "--target-width",
                        finalWidth
                    );

                    bar.style.width = "0";

                    requestAnimationFrame(() => {
                        bar.classList.add(
                            "animate-leave"
                        );
                    });

                });

                dashboardObserver.disconnect();

            });

        },
        {
            threshold: 0.25,
        }
    );

    if (dashboard) {
        dashboardObserver.observe(dashboard);
    }


    /* ==============================================
       BUTTON RIPPLE
    ============================================== */

    const buttons = document.querySelectorAll(
        ".button, .nav-button"
    );

    buttons.forEach((button) => {

        button.addEventListener(
            "click",
            function (event) {

                const ripple =
                    document.createElement("span");

                ripple.className =
                    "button-ripple";

                const rect =
                    this.getBoundingClientRect();

                const size = Math.max(
                    rect.width,
                    rect.height
                );

                ripple.style.width =
                    `${size}px`;

                ripple.style.height =
                    `${size}px`;

                ripple.style.left =
                    `${event.clientX - rect.left - size / 2}px`;

                ripple.style.top =
                    `${event.clientY - rect.top - size / 2}px`;

                this.appendChild(ripple);

                setTimeout(() => {
                    ripple.remove();
                }, 600);

            }
        );

    });


    /* ==============================================
       ACTIVE NAV LINK
    ============================================== */

    const sections = document.querySelectorAll(
        "#platform, #workflow, #why"
    );

    const navLinks = document.querySelectorAll(
        ".main-nav a"
    );

    const sectionObserver =
        new IntersectionObserver(
            (entries) => {

                entries.forEach((entry) => {

                    if (!entry.isIntersecting) {
                        return;
                    }

                    navLinks.forEach((link) => {

                        link.classList.remove(
                            "active"
                        );

                        const href =
                            link.getAttribute("href");

                        if (
                            href ===
                            `#${entry.target.id}`
                        ) {
                            link.classList.add(
                                "active"
                            );
                        }

                    });

                });

            },
            {
                rootMargin:
                    "-35% 0px -55% 0px",
            }
        );

    sections.forEach((section) => {
        sectionObserver.observe(section);
    });


    /* ==============================================
       CARD POINTER MOVEMENT
    ============================================== */

    document
        .querySelectorAll(".platform-card")
        .forEach((card) => {

            card.addEventListener(
                "mousemove",
                (event) => {

                    const rect =
                        card.getBoundingClientRect();

                    const x =
                        event.clientX -
                        rect.left;

                    const y =
                        event.clientY -
                        rect.top;

                    card.style.setProperty(
                        "--mouse-x",
                        `${x}px`
                    );

                    card.style.setProperty(
                        "--mouse-y",
                        `${y}px`
                    );

                }
            );

        });

});