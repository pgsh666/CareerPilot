import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import "./home/home.css";
import "./ui/business.css";
import "./ui/theme.css";
import "./ui/pageMotion.css";
import "./ui/disclosureMotion.css";
import { installFeedback } from "./core/feedback";

installFeedback();
createApp(App).use(router).mount("#app");
