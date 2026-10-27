import { preloadRegion, setRegionLoader } from "morphicons/dom";
import * as region from "morphicons/region";

// Initialize once, before any icon mounts. No CDN or lazy network requests,
// including when the application is exported into one offline HTML file.
setRegionLoader(async () => region);
void preloadRegion();
