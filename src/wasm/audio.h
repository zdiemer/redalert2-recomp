/* Included after the existing DirectSound mixer. Only the output device
 * changes: the same PCM and play cursors go to browser Web Audio. */
#include <emscripten.h>
#include <unistd.h>

static void *web_audio_thread(void *unused) {
    (void)unused;
    int16_t pcm[2048];
    double next = emscripten_get_now();
    for (;;) {
        mix(NULL, (Uint8 *)pcm, sizeof pcm);
        MAIN_THREAD_EM_ASM({
            const ctx = Module.ra2Audio;
            if (!ctx || ctx.state !== 'running') return;
            const buffer = ctx.createBuffer(2, 1024, 44100);
            const left = buffer.getChannelData(0); const right = buffer.getChannelData(1);
            let nonzero = false;
            for (let i = 0; i < 1024; i++) {
                left[i] = HEAP16[($0 >> 1) + 2*i] / 32768;
                right[i] = HEAP16[($0 >> 1) + 2*i + 1] / 32768;
                if (left[i] || right[i]) nonzero = true;
            }
            const source = ctx.createBufferSource();
            source.buffer = buffer; source.connect(ctx.destination);
            const when = Math.max(ctx.currentTime + 0.03, Module.ra2AudioNext || 0);
            source.start(when); Module.ra2AudioNext = when + 1024/44100;
            if (nonzero) Module.ra2AudioChunks = (Module.ra2AudioChunks || 0) + 1;
        }, pcm);
        next += 1024000.0 / OUT_RATE;
        double delay = next - emscripten_get_now();
        if (delay > 0) usleep((unsigned)(delay * 1000));
        else if (delay < -100) next = emscripten_get_now();
    }
    return NULL;
}

static int audio_open(void) {
    if (g_audio_ok >= 0) return g_audio_ok;
    g_audio_ok = 0;
    pthread_t thread;
    if (pthread_create(&thread, NULL, web_audio_thread, NULL) != 0) return 0;
    pthread_detach(thread);
    fprintf(stderr, "[dsound] Web Audio, %d Hz stereo\n", OUT_RATE);
    return g_audio_ok = 1;
}
