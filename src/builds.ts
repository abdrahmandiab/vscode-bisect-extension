/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See LICENSE in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import chalk from 'chalk';
import { dirname, join } from 'node:path';
import { rmSync, readFileSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { Arch, arch, Flavor, isDockerCliFlavor, LOGGER, Platform, platform, Quality, Runtime } from './constants.js';
import { fileGet, jsonGet } from './fetch.js';
import { computeSHA256, exists, getBuildPath, unzip } from './files.js';

export interface IBuildKind {
    readonly runtime: Runtime;
    readonly quality: Quality;
    readonly flavor: Flavor;
    readonly platform?: Platform;
    readonly arch?: Arch;
}

export interface IBuild extends IBuildKind {
    readonly commit: string;
    readonly date?: string | number; // Timestamp or ISO string
    readonly version?: string; // Helpful for VSCodium tags
    readonly assets?: any; // VSCodium Asset URLs
}

interface IBuildMetadata {
    readonly url: string;
    readonly version: string;
    readonly productVersion: string;
    readonly sha256hash: string;
}

class Builds {

    private loadHistory(quality: Quality): any[] {
        let filename;
        if (quality === Quality.VSCodiumInsider) {
            filename = 'vscodium_insider_history.json';
        } else {
            filename = quality === Quality.Insider ? 'vscode_insider_history.json' : 'vscode_stable_history.json';
        }

        const path = join(process.cwd(), filename);
        try {
            const content = readFileSync(path, 'utf8');
            const history = JSON.parse(content);
            // JSON is Oldest -> Newest (based on generation script)
            // We want Newest -> Oldest for the UI/Bisecter (index 0 = newest)
            // VSCodium JSON might be Newest->Oldest already? Let's assume consistent scraper behavior.
            // My scrapers produced Ascending (Old -> New). So Reverse is correct.
            return history.slice().reverse();
        } catch (e) {
            console.error(`Failed to load history from ${path}: ${e}`);
            return [];
        }
    }

    async fetchBuildByVersion({ runtime, quality, flavor }: IBuildKind, version: string): Promise<IBuild> {
        // Try local history first
        const history = this.loadHistory(quality);
        const match = history.find((b: any) => b.version === version);
        if (match) {
            return { runtime, commit: match.commit, quality, flavor };
        }

        let meta;
        if (quality === 'insider') {
            meta = await jsonGet<IBuildMetadata>(`https://update.code.visualstudio.com/api/versions/${version}.0-insider/${this.getBuildApiName({ runtime, quality, flavor })}/insider?released=true`);
        } else {
            meta = await jsonGet<IBuildMetadata>(`https://update.code.visualstudio.com/api/versions/${version}.0/${this.getBuildApiName({ runtime, quality, flavor })}/stable?released=true`);
        }

        return { runtime, commit: meta.version, quality, flavor };
    }

    async fetchBuilds({ runtime, quality, flavor }: IBuildKind, goodCommit?: string, badCommit?: string, releasedOnly?: boolean, excludeCommits?: string[], useDiscovery = false): Promise<IBuild[]> {

        // Fetch all released builds (from Local JSON or API depending on useDiscovery)
        const allBuilds = await this.fetchAllBuilds({ runtime, quality, flavor }, releasedOnly, useDiscovery);

        const dateRegex = /^\d{1,2}-\d{1,2}-\d{4}$/;

        if (typeof goodCommit === 'string' && dateRegex.test(goodCommit)) {
            goodCommit = this.resolveDateToBuild(goodCommit, allBuilds);
        }

        if (typeof badCommit === 'string' && dateRegex.test(badCommit)) {
            badCommit = this.resolveDateToBuild(badCommit, allBuilds);
        }

        let goodCommitIndex = allBuilds.length - 1;  // last build (oldest) by default
        let badCommitIndex = 0;                      // first build (newest) by default

        if (typeof goodCommit === 'string') {
            const candidateGoodCommitIndex = this.indexOf(goodCommit, allBuilds);
            if (typeof candidateGoodCommitIndex !== 'number') {
                throw new Error(`Provided good commit ${chalk.green(goodCommit)} was not found in the list of builds. It is either invalid or too old.`);
            }
            goodCommitIndex = candidateGoodCommitIndex;
        }

        if (typeof badCommit === 'string') {
            const candidateBadCommitIndex = this.indexOf(badCommit, allBuilds);
            if (typeof candidateBadCommitIndex !== 'number') {
                throw new Error(`Provided bad commit ${chalk.green(badCommit)} was not found in the list of builds. It is either invalid or too old.`);
            }
            badCommitIndex = candidateBadCommitIndex;
        }

        if (badCommitIndex >= goodCommitIndex) {
            throw new Error(`Provided bad commit ${chalk.green(badCommit)} cannot be older or same as good commit ${chalk.green(goodCommit)}.`);
        }

        // Build a range based on the bad and good commits if any
        let buildsInRange = allBuilds.slice(badCommitIndex, goodCommitIndex + 1);

        // Filter out excluded commits if any
        if (excludeCommits && excludeCommits.length > 0) {
            const excludeSet = new Set(excludeCommits);
            const originalLength = buildsInRange.length;
            buildsInRange = buildsInRange.filter(build => !excludeSet.has(build.commit));

            if (buildsInRange.length !== originalLength) {
                const excludedCount = originalLength - buildsInRange.length;
                LOGGER.log(`${chalk.gray('[build]')} excluded ${chalk.green(excludedCount)} commit${excludedCount === 1 ? '' : 's'} from bisecting`);
            }
        }

        // Drop those builds that are not on main branch
        return buildsInRange;
    }

    private resolveDateToBuild(dateStr: string, builds: IBuild[]): string {
        // Parse dateStr (DD-MM-YYYY)
        const [day, month, year] = dateStr.split('-').map(Number);
        const targetTime = new Date(year, month - 1, day).getTime();

        let bestBuild: IBuild | undefined;
        let minDiff = Number.MAX_VALUE;

        for (const build of builds) {
            if (!build.date) continue;

            let buildTime: number;
            if (typeof build.date === 'number') {
                buildTime = build.date;
            } else {
                buildTime = new Date(build.date).getTime();
            }

            const diff = Math.abs(buildTime - targetTime);
            if (diff < minDiff) {
                minDiff = diff;
                bestBuild = build;
            }
        }

        if (bestBuild) {
            const d = new Date(typeof bestBuild.date === 'number' ? bestBuild.date : bestBuild.date!).toISOString().split('T')[0];
            LOGGER.log(`${chalk.gray('[build]')} resolved date ${chalk.green(dateStr)} to build ${chalk.green(bestBuild.version || bestBuild.commit)} (${d})`);
            return bestBuild.commit;
        }

        throw new Error(`Could not resolve date ${dateStr} to any build.`);
    }

    private indexOf(commit: string, builds: IBuild[]): number | undefined {
        for (let i = 0; i < builds.length; i++) {
            const build = builds[i];
            if (build.commit === commit) {
                return i;
            }
        }

        return undefined;
    }

    private async fetchAllBuilds({ runtime, quality, flavor }: IBuildKind, releasedOnly = false, useDiscovery = false): Promise<IBuild[]> {
        // Use Local History JSON instead of Discovery API (unless useDiscovery is enabled)
        if (!useDiscovery) {
            const history = this.loadHistory(quality);
            if (history.length > 0) {
                LOGGER.log(`${chalk.gray('[build]')} loaded ${chalk.green(history.length)} builds from local history json...`);
                return history.map((h: any) => ({ commit: h.commit, date: h.date, version: h.version, assets: h.assets, runtime, quality, flavor }));
            }
        }

        // Fallback to API if JSON fails/empty OR if useDiscovery is true
        const url = `https://update.code.visualstudio.com/api/commits/${quality}/${this.getBuildApiName({ runtime, quality, flavor })}?released=${releasedOnly}`;
        LOGGER.log(`${chalk.gray('[build]')} fetching all builds from ${chalk.green(url)}...`);
        const commits = await jsonGet<Array<string>>(url);

        return commits.map(commit => ({ commit, runtime, quality, flavor }));
    }

    private getBuildApiName({ runtime, flavor, platform: buildPlatform, arch: buildArch }: IBuildKind): string {
        const effectivePlatform = buildPlatform ?? platform;
        const effectiveArch = buildArch ?? arch;

        // Server
        if (runtime === Runtime.WebLocal || runtime === Runtime.WebRemote) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                case Platform.MacOSArm:
                    return 'server-darwin-web';
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    return `server-linux-${effectiveArch}-web`;
                case Platform.WindowsX64:
                case Platform.WindowsArm:
                    return `server-win32-${effectiveArch}-web`;
            }
        }

        // Desktop / CLI
        switch (effectivePlatform) {
            case Platform.MacOSX64:
                return flavor === Flavor.DarwinUniversal ? 'darwin-universal' : 'darwin';
            case Platform.MacOSArm:
                return flavor === Flavor.DarwinUniversal ? 'darwin-universal' : `darwin-${Arch.Arm64}`;
            case Platform.LinuxX64:
            case Platform.LinuxArm:
                return `linux-${effectiveArch}`;
            case Platform.WindowsX64:
            case Platform.WindowsArm:
                return `win32-${effectiveArch}`;
        }
    }

    async downloadAndExtractBuild(build: IBuild, options?: { forceReDownload: boolean }): Promise<string | undefined> {
        const { runtime, commit, quality, flavor } = build;

        if (quality === Quality.VSCodiumInsider) {
            return this.downloadAndExtractVSCodium(build, options);
        }

        if (isDockerCliFlavor(flavor)) {
            return undefined; // CLIs running in docker are handled differently
        }

        const buildName = await this.getBuildDownloadName({ runtime, commit, quality, flavor });

        const path = join(getBuildPath(commit, quality, flavor), buildName);

        const pathExists = await exists(path);
        if (pathExists && !options?.forceReDownload) {
            LOGGER.trace(`${chalk.gray('[build]')} using ${chalk.green(path)} for the next build to try`);

            return path; // assume the build is cached
        }

        if (pathExists && options?.forceReDownload) {
            LOGGER.log(`${chalk.gray('[build]')} deleting ${chalk.green(getBuildPath(commit, quality, flavor))} and retrying download`);
            rmSync(getBuildPath(commit, quality, flavor), { recursive: true });
        }

        // Download
        const { url, sha256hash: expectedSHA256 } = await this.fetchBuildMeta({ runtime, commit, quality, flavor });
        LOGGER.log(`${chalk.gray('[build]')} downloading build from ${chalk.green(url)}...`);
        await fileGet(url, path);

        // Validate SHA256 Checksum
        const computedSHA256 = await computeSHA256(path);
        if (expectedSHA256 !== computedSHA256) {
            throw new Error(`${chalk.gray('[build]')} ${chalk.red('✘')} expected SHA256 checksum (${expectedSHA256}) does not match with download (${computedSHA256})`);
        } else {
            LOGGER.log(`${chalk.gray('[build]')} ${chalk.green('✔︎')} expected SHA256 checksum matches with download`);
        }

        // Unzip (unless its an installer)
        if (flavor === Flavor.Default || flavor === Flavor.Cli || flavor === Flavor.DarwinUniversal) {
            let destination: string;
            if ((runtime === Runtime.DesktopLocal || runtime === Runtime.WebLocal) && flavor === Flavor.Default && (platform === Platform.WindowsX64 || platform === Platform.WindowsArm)) {
                // zip does not contain a single top level folder to use...
                destination = path.substring(0, path.lastIndexOf('.zip'));
            } else {
                // zip contains a single top level folder to use
                destination = dirname(path);
            }
            LOGGER.log(`${chalk.gray('[build]')} unzipping ${chalk.green(path)} to ${chalk.green(destination)}...`);
            await unzip(path, destination);

            return destination;
        }

        return path;
    }

    private async downloadAndExtractVSCodium(build: IBuild, options?: { forceReDownload: boolean }): Promise<string> {
        const { commit, quality, flavor, assets, version } = build;

        if (!assets) {
            throw new Error(`VSCodium build ${version} (commit ${commit}) is missing assets map.`);
        }

        // Determine URL based on platform/arch
        let url: string | undefined;
        let ext = '.zip';

        if (platform === Platform.MacOSArm) {
            url = assets['darwin_arm64'];
        } else if (platform === Platform.MacOSX64) {
            url = assets['darwin_x64'];
        } else if (platform === Platform.LinuxX64) {
            url = assets['linux_x64'];
            ext = '.tar.gz';
        } else if (platform === Platform.LinuxArm) {
            url = assets['linux_arm64'];
            ext = '.tar.gz';
        }

        if (!url) {
            throw new Error(`No VSCodium asset found for current platform (${platform}) in build ${version}`);
        }

        const buildName = `VSCodium-${version}${ext}`;
        const folder = getBuildPath(commit, quality, flavor);
        const zipPath = join(folder, buildName);

        if (await exists(folder) && !options?.forceReDownload) {
            LOGGER.trace(`${chalk.gray('[build]')} using VSCodium cached at ${chalk.green(folder)}`);
            return folder;
        }

        if (await exists(folder)) {
            rmSync(folder, { recursive: true });
        }

        LOGGER.log(`${chalk.gray('[build]')} downloading VSCodium from ${chalk.green(url)}...`);
        await fileGet(url, zipPath);

        // Manual Unzip (Spawn)
        const destination = folder;
        LOGGER.log(`${chalk.gray('[build]')} extracting VSCodium to ${chalk.green(destination)}...`);

        if (platform === Platform.MacOSArm || platform === Platform.MacOSX64) {
            const result = spawnSync('unzip', ['-q', zipPath, '-d', destination]);
            if (result.error || result.status !== 0) {
                throw new Error(`Failed to unzip VSCodium: ${result.error || (result.stderr ? result.stderr.toString() : 'Unknown error')}`);
            }

            // App usually in 'VSCodium.app'
            const appPath = join(destination, 'VSCodium.app');

            if (await exists(appPath)) {
                // Patch product.json
                const productJsonPath = join(appPath, 'Contents', 'Resources', 'app', 'product.json');
                if (await exists(productJsonPath)) {
                    LOGGER.log(`Patching product.json at ${productJsonPath}`);
                    const productData = JSON.parse(readFileSync(productJsonPath, 'utf8'));

                    // Inject Extensions Gallery
                    productData.extensionsGallery = {
                        serviceUrl: "https://marketplace.visualstudio.com/_apis/public/gallery",
                        cacheUrl: "https://vscode.blob.core.windows.net/gallery/index",
                        itemUrl: "https://marketplace.visualstudio.com/items",
                        controlUrl: "",
                        recommendationsUrl: ""
                    };

                    // Inject Quality
                    productData.quality = 'insider';
                    productData.nameShort = 'VSCodium - Bisect';

                    writeFileSync(productJsonPath, JSON.stringify(productData, null, 4));
                }

                // Remove Quarantine
                spawnSync('xattr', ['-r', '-d', 'com.apple.quarantine', appPath]);

                // Codesign
                spawnSync('codesign', ['--force', '--deep', '--sign', '-', appPath]);
            }
        } else {
            await unzip(zipPath, destination);
        }

        return destination;
    }

    private async getBuildDownloadName({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch }: IBuild): Promise<string> {
        const effectivePlatform = buildPlatform ?? platform;
        const effectiveArch = buildArch ?? arch;

        // Server
        if (runtime === Runtime.WebLocal || runtime === Runtime.WebRemote) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                case Platform.MacOSArm:
                    return `vscode-server-darwin-${effectiveArch}-web.zip`;
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    return `vscode-server-linux-${effectiveArch}-web.tar.gz`;
                case Platform.WindowsX64:
                case Platform.WindowsArm:
                    return `vscode-server-win32-${effectiveArch}-web.zip`;
            }
        }

        // Desktop
        if (flavor !== Flavor.Cli) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                    return flavor === Flavor.DarwinUniversal ? 'VSCode-darwin-universal.zip' : 'VSCode-darwin.zip';
                case Platform.MacOSArm:
                    return flavor === Flavor.DarwinUniversal ? 'VSCode-darwin-universal.zip' : `VSCode-darwin-${Arch.Arm64}.zip`;
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    return (await this.fetchBuildMeta({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch })).url.split('/').pop()!; // e.g. https://az764295.vo.msecnd.net/insider/807bf598bea406dcb272a9fced54697986e87768/code-insider-x64-1639979337.tar.gz
                case Platform.WindowsX64:
                case Platform.WindowsArm: {
                    const buildMeta = await this.fetchBuildMeta({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch });
                    switch (flavor) {
                        case Flavor.Default:
                            return `VSCode-win32-${effectiveArch}-${buildMeta.productVersion}.zip`;
                        case Flavor.WindowsSystemInstaller:
                            return `VSCodeSetup-${effectiveArch}-${buildMeta.productVersion}.exe`;
                        case Flavor.WindowsUserInstaller:
                            return `VSCodeUserSetup-${effectiveArch}-${buildMeta.productVersion}.exe`;
                    }
                }
            }
        }

        // CLI
        switch (effectivePlatform) {
            case Platform.MacOSX64:
                return 'vscode_cli_darwin_x64_cli.zip';
            case Platform.MacOSArm:
                return 'vscode_cli_darwin_arm64_cli.zip';
            case Platform.LinuxX64:
                return 'vscode_cli_linux_x64_cli.tar.gz';
            case Platform.LinuxArm:
                return 'vscode_cli_linux_arm64_cli.tar.gz';
            case Platform.WindowsX64:
                return 'vscode_cli_win32_x64_cli.zip';
            case Platform.WindowsArm:
                return 'vscode_cli_win32_arm64_cli.zip';
        }
    }

    private async getBuildName({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch }: IBuild): Promise<string> {
        const effectivePlatform = buildPlatform ?? platform;
        const effectiveArch = buildArch ?? arch;

        // Server
        if (runtime === Runtime.WebLocal || runtime === Runtime.WebRemote) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                case Platform.MacOSArm:
                    return `vscode-server-darwin-${effectiveArch}-web`;
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    return `vscode-server-linux-${effectiveArch}-web`;
                case Platform.WindowsX64:
                case Platform.WindowsArm:
                    return `vscode-server-win32-${effectiveArch}-web`;
            }
        }

        // Desktop
        if (flavor !== Flavor.Cli) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                case Platform.MacOSArm:
                    return quality === 'insider' ? 'Visual Studio Code - Insiders.app' : 'Visual Studio Code.app';
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    return `VSCode-linux-${effectiveArch}`;
                case Platform.WindowsX64:
                case Platform.WindowsArm: {
                    const buildMeta = await this.fetchBuildMeta({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch });

                    return `VSCode-win32-${effectiveArch}-${buildMeta.productVersion}`;
                }
            }
        }

        // CLI
        return quality === 'insider' ? 'code-insiders' : 'code';
    }

    private async fetchBuildMeta({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch }: IBuild): Promise<IBuildMetadata> {
        try {
            return await jsonGet<IBuildMetadata>(`https://update.code.visualstudio.com/api/versions/commit:${commit}/${this.getPlatformName({ runtime, quality, flavor, platform: buildPlatform, arch: buildArch })}/${quality}`);
        } catch (error: any) {
            // Fallback Logic for ARM64 -> x64
            const effectivePlatform = buildPlatform ?? platform;
            if (effectivePlatform === Platform.MacOSArm && quality === 'stable') {
                // If we failed to get metadata for ARM64 Stable, try x64 Stable
                try {
                    return await jsonGet<IBuildMetadata>(`https://update.code.visualstudio.com/api/versions/commit:${commit}/${this.getPlatformName({ runtime, quality, flavor, platform: Platform.MacOSX64, arch: Arch.X64 })}/${quality}`);
                } catch (ignore) {
                    throw error; // If x64 also fails, throw original error
                }
            }
            throw error;
        }
    }

    private getPlatformName({ runtime, flavor, platform: buildPlatform, arch: buildArch }: IBuildKind): string {
        const effectivePlatform = buildPlatform ?? platform;
        const effectiveArch = buildArch ?? arch;

        // Server
        if (runtime === Runtime.WebLocal || runtime === Runtime.WebRemote) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                    return 'server-darwin-web';
                case Platform.MacOSArm:
                    return `server-darwin-${Arch.Arm64}-web`;
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    return `server-linux-${effectiveArch}-web`;
                case Platform.WindowsX64:
                case Platform.WindowsArm:
                    return `server-win32-${effectiveArch}-web`;
            }
        }

        // Desktop
        if (flavor !== Flavor.Cli) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                    return flavor === Flavor.DarwinUniversal ? 'darwin-universal' : 'darwin';
                case Platform.MacOSArm:
                    return flavor === Flavor.DarwinUniversal ? 'darwin-universal' : `darwin-${Arch.Arm64}`;
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    switch (flavor) {
                        case Flavor.Default:
                            return `linux-${effectiveArch}`;
                        case Flavor.LinuxDeb:
                            return `linux-deb-${effectiveArch}`;
                        case Flavor.LinuxRPM:
                            return `linux-rpm-${effectiveArch}`;
                        case Flavor.LinuxSnap:
                            return `linux-snap-${effectiveArch}`;
                    }
                case Platform.WindowsX64:
                case Platform.WindowsArm:
                    switch (flavor) {
                        case Flavor.Default:
                            return `win32-${effectiveArch}-archive`;
                        case Flavor.WindowsUserInstaller:
                            return `win32-${effectiveArch}-user`;
                        case Flavor.WindowsSystemInstaller:
                            return `win32-${effectiveArch}`;
                    }
            }
        }

        // CLI
        switch (effectivePlatform) {
            case Platform.MacOSX64:
            case Platform.MacOSArm:
                return `cli-darwin-${effectiveArch}`;
            case Platform.LinuxX64:
            case Platform.LinuxArm:
                return `cli-linux-${effectiveArch}`;
            case Platform.WindowsX64:
            case Platform.WindowsArm:
                return `cli-win32-${effectiveArch}`;
        }
    }

    async getBuildExecutable({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch }: IBuild): Promise<string> {
        const buildPath = getBuildPath(commit, quality, flavor);
        const buildName = await builds.getBuildName({ runtime, commit, quality, flavor, platform: buildPlatform, arch: buildArch });
        const effectivePlatform = buildPlatform ?? platform;

        // Server
        if (runtime === Runtime.WebLocal || runtime === Runtime.WebRemote) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                case Platform.MacOSArm:
                case Platform.LinuxX64:
                case Platform.LinuxArm: {
                    const oldLocation = join(buildPath, buildName, 'server.sh');
                    if (await exists(oldLocation)) {
                        return oldLocation; // only valid until 1.64.x
                    }

                    return join(buildPath, buildName, 'bin', quality === 'insider' ? 'code-server-insiders' : 'code-server');
                }
                case Platform.WindowsX64:
                case Platform.WindowsArm: {
                    const oldLocation = join(buildPath, buildName, 'server.cmd');
                    if (await exists(oldLocation)) {
                        return oldLocation; // only valid until 1.64.x
                    }

                    return join(buildPath, buildName, buildName, 'bin', quality === 'insider' ? 'code-server-insiders.cmd' : 'code-server.cmd');
                }
            }
        }

        // Desktop
        if (flavor !== Flavor.Cli) {
            switch (effectivePlatform) {
                case Platform.MacOSX64:
                case Platform.MacOSArm:
                    return join(buildPath, buildName, 'Contents', 'MacOS', 'Electron');
                case Platform.LinuxX64:
                case Platform.LinuxArm:
                    return join(buildPath, buildName, quality === 'insider' ? 'code-insiders' : 'code')
                case Platform.WindowsX64:
                case Platform.WindowsArm:
                    return join(buildPath, buildName, quality === 'insider' ? 'Code - Insiders.exe' : 'Code.exe');
            }
        }

        // CLI
        switch (effectivePlatform) {
            case Platform.MacOSX64:
            case Platform.MacOSArm:
            case Platform.LinuxX64:
            case Platform.LinuxArm:
                return join(buildPath, buildName);
            case Platform.WindowsX64:
            case Platform.WindowsArm:
                return join(buildPath, `${buildName}.exe`);
        }
    }
}

export const builds = new Builds();
