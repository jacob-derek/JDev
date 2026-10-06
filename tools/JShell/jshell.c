#include <gtk/gtk.h>
#include <gio/gio.h>
#include <string.h>

typedef struct {
    GtkWidget *window;
    GtkTextView *saida;
    GtkEntry *entrada;
    GtkLabel *status_caminho;

    GSubprocess *backend;
    GDataInputStream *backend_saida;
    GOutputStream *backend_entrada;
} AppState;


/* ============================================================
 * UTILIDADES DA GUI
 * ============================================================ */

static void adicionar_saida(AppState *app, const gchar *texto)
{
    GtkTextBuffer *buffer;
    GtkTextIter fim;
    GtkTextMark *marca;

    buffer = gtk_text_view_get_buffer(app->saida);
    gtk_text_buffer_get_end_iter(buffer, &fim);

    gtk_text_buffer_insert(buffer, &fim, texto, -1);

    marca = gtk_text_buffer_create_mark(
        buffer,
        NULL,
        &fim,
        FALSE
    );

    gtk_text_view_scroll_mark_onscreen(app->saida, marca);
    gtk_text_buffer_delete_mark(buffer, marca);
}


static void adicionar_linha(AppState *app, const gchar *texto)
{
    gchar *linha = g_strdup_printf("%s\n", texto);
    adicionar_saida(app, linha);
    g_free(linha);
}


static void limpar_saida(AppState *app)
{
    GtkTextBuffer *buffer;

    buffer = gtk_text_view_get_buffer(app->saida);
    gtk_text_buffer_set_text(buffer, "", -1);
}


/* ============================================================
 * LEITURA DO BACKEND
 * ============================================================ */

static void ler_backend(
    GObject *source_object,
    GAsyncResult *resultado,
    gpointer user_data
)
{
    AppState *app = user_data;
    GError *erro = NULL;
    gsize tamanho = 0;

    gchar *linha = g_data_input_stream_read_line_finish(
        G_DATA_INPUT_STREAM(source_object),
        resultado,
        &tamanho,
        &erro
    );

    if (erro != NULL) {
        adicionar_linha(
            app,
            "Erro na comunicação com o backend."
        );

        g_error_free(erro);
        gtk_widget_set_sensitive(GTK_WIDGET(app->entrada), FALSE);
        return;
    }

    /* Backend encerrou a saída. */
    if (linha == NULL) {
        gtk_widget_set_sensitive(GTK_WIDGET(app->entrada), FALSE);
        return;
    }

    /*
     * Protocolo simples:
     *
     * RESULT
     * texto...
     * END
     *
     * CLEAR e EXIT são enviados como comandos especiais
     * dentro do bloco RESULT.
     */

    if (g_strcmp0(linha, "RESULT") == 0) {
        g_free(linha);

        g_data_input_stream_read_line_async(
            app->backend_saida,
            G_PRIORITY_DEFAULT,
            NULL,
            ler_backend,
            app
        );

        return;
    }

    if (g_strcmp0(linha, "END") == 0) {
        g_free(linha);

        g_data_input_stream_read_line_async(
            app->backend_saida,
            G_PRIORITY_DEFAULT,
            NULL,
            ler_backend,
            app
        );

        return;
    }

    if (g_strcmp0(linha, "__JSHELL_CLEAR__") == 0) {
        limpar_saida(app);
    } else {
        adicionar_linha(app, linha);
    }

    g_free(linha);

    g_data_input_stream_read_line_async(
        app->backend_saida,
        G_PRIORITY_DEFAULT,
        NULL,
        ler_backend,
        app
    );
}


/* ============================================================
 * COMUNICAÇÃO COM PYTHON
 * ============================================================ */

static gboolean iniciar_backend(AppState *app)
{
    gchar *backend_path;
    GError *erro = NULL;

    backend_path = g_build_filename(
        g_get_current_dir(),
        "jshell-core.py",
        NULL
    );

    app->backend = g_subprocess_new(
        G_SUBPROCESS_FLAGS_STDIN_PIPE |
        G_SUBPROCESS_FLAGS_STDOUT_PIPE |
        G_SUBPROCESS_FLAGS_STDERR_MERGE,
        &erro,
        "python3",
        backend_path,
        NULL
    );

    g_free(backend_path);

    if (erro != NULL) {
        adicionar_linha(
            app,
            "ERRO: não foi possível iniciar jshell-core.py"
        );

        adicionar_linha(
            app,
            erro->message
        );

        g_error_free(erro);
        return FALSE;
    }

    app->backend_entrada =
        g_subprocess_get_stdin_pipe(app->backend);

    app->backend_saida = g_data_input_stream_new(
        g_subprocess_get_stdout_pipe(app->backend)
    );

    /*
     * Começa a escutar o stdout do Python sem bloquear
     * a interface GTK.
     */
    g_data_input_stream_read_line_async(
        app->backend_saida,
        G_PRIORITY_DEFAULT,
        NULL,
        ler_backend,
        app
    );

    return TRUE;
}


static gboolean enviar_comando(
    AppState *app,
    const gchar *comando
)
{
    gchar *linha;
    gsize escritos = 0;
    GError *erro = NULL;

    if (app->backend_entrada == NULL) {
        adicionar_linha(
            app,
            "ERRO: backend não está conectado."
        );
        return FALSE;
    }

    linha = g_strdup_printf("%s\n", comando);

    if (!g_output_stream_write_all(
            app->backend_entrada,
            linha,
            strlen(linha),
            &escritos,
            NULL,
            &erro
        )) {

        adicionar_linha(
            app,
            "ERRO ao enviar comando para o backend."
        );

        if (erro != NULL) {
            adicionar_linha(app, erro->message);
            g_error_free(erro);
        }

        g_free(linha);
        return FALSE;
    }

    g_output_stream_flush(
        app->backend_entrada,
        NULL,
        NULL
    );

    g_free(linha);

    return TRUE;
}


/* ============================================================
 * INPUT DE COMANDOS
 * ============================================================ */

static void executar_comando(
    GtkEntry *entrada,
    gpointer dados
)
{
    AppState *app = dados;
    const gchar *comando;
    gchar *linha;

    comando = gtk_entry_get_text(entrada);

    if (comando == NULL || *comando == '\0') {
        return;
    }

    /*
     * Mostra o comando digitado imediatamente.
     */
    linha = g_strdup_printf("$ %s\n", comando);
    adicionar_saida(app, linha);
    g_free(linha);

    enviar_comando(app, comando);

    gtk_entry_set_text(entrada, "");
}


/* ============================================================
 * FECHAMENTO
 * ============================================================ */

static void fechar_backend(
    GtkWidget *widget,
    gpointer dados
)
{
    AppState *app = dados;

    if (app->backend != NULL &&
        !g_subprocess_get_if_exited(app->backend)) {

        g_subprocess_force_exit(app->backend);
    }
}


/* ============================================================
 * ESTILO
 * ============================================================ */

static void aplicar_estilo(void)
{
    GtkCssProvider *css;
    GdkScreen *screen;

    css = gtk_css_provider_new();

    gtk_css_provider_load_from_data(
        css,

        "* {"
        "  font-family: Sans;"
        "}"

        "#janela {"
        "  background: #1e1e2e;"
        "}"

        "#cabecalho {"
        "  background: #181825;"
        "  padding: 14px 18px;"
        "}"

        "#titulo {"
        "  color: #cdd6f4;"
        "  font-size: 20px;"
        "  font-weight: bold;"
        "}"

        "#subtitulo {"
        "  color: #6c7086;"
        "  font-size: 12px;"
        "}"

        "#terminal {"
        "  background: #1e1e2e;"
        "  color: #cdd6f4;"
        "  font-family: monospace;"
        "  font-size: 14px;"
        "  padding: 12px;"
        "}"

        "#comando {"
        "  background: #181825;"
        "  color: #cdd6f4;"
        "  border: 1px solid #313244;"
        "  border-radius: 6px;"
        "  padding: 9px;"
        "  font-family: monospace;"
        "}"

        "#comando:focus {"
        "  border-color: #89b4fa;"
        "}"

        "#prompt {"
        "  color: #89b4fa;"
        "  font-family: monospace;"
        "  font-size: 15px;"
        "  padding-left: 12px;"
        "}"

        "#status {"
        "  background: #181825;"
        "  color: #6c7086;"
        "  padding: 7px 12px;"
        "  font-size: 11px;"
        "}",

        -1,
        NULL
    );

    screen = gdk_screen_get_default();

    gtk_style_context_add_provider_for_screen(
        screen,
        GTK_STYLE_PROVIDER(css),
        GTK_STYLE_PROVIDER_PRIORITY_APPLICATION
    );

    g_object_unref(css);
}


/* ============================================================
 * CONSTRUÇÃO DA JANELA
 * ============================================================ */

static void ativar(
    GtkApplication *aplicacao,
    gpointer dados
)
{
    AppState *app;
    GtkWidget *janela;
    GtkWidget *principal;
    GtkWidget *cabecalho;
    GtkWidget *titulo_box;
    GtkWidget *titulo;
    GtkWidget *subtitulo;
    GtkWidget *scroll;
    GtkWidget *linha_comando;
    GtkWidget *prompt;
    GtkWidget *entrada;
    GtkWidget *status;
    GtkWidget *status_caminho;
    GtkWidget *status_info;

    app = g_new0(AppState, 1);

    janela = gtk_application_window_new(aplicacao);
    aplicar_estilo();

    gtk_window_set_title(
        GTK_WINDOW(janela),
        "JShell — JDev"
    );

    gtk_window_set_default_size(
        GTK_WINDOW(janela),
        1000,
        650
    );

    gtk_window_set_position(
        GTK_WINDOW(janela),
        GTK_WIN_POS_CENTER
    );

    gtk_widget_set_name(janela, "janela");

    app->window = janela;

    /* --------------------------------------------------------
     * CONTAINER PRINCIPAL
     * -------------------------------------------------------- */

    principal = gtk_box_new(
        GTK_ORIENTATION_VERTICAL,
        0
    );

    gtk_container_add(
        GTK_CONTAINER(janela),
        principal
    );

    /* --------------------------------------------------------
     * CABEÇALHO
     * -------------------------------------------------------- */

    cabecalho = gtk_box_new(
        GTK_ORIENTATION_HORIZONTAL,
        8
    );

    gtk_widget_set_name(
        cabecalho,
        "cabecalho"
    );

    gtk_box_pack_start(
        GTK_BOX(principal),
        cabecalho,
        FALSE,
        FALSE,
        0
    );

    titulo_box = gtk_box_new(
        GTK_ORIENTATION_VERTICAL,
        2
    );

    gtk_box_pack_start(
        GTK_BOX(cabecalho),
        titulo_box,
        FALSE,
        FALSE,
        0
    );

    titulo = gtk_label_new("JShell");

    gtk_widget_set_name(
        titulo,
        "titulo"
    );

    gtk_widget_set_halign(
        titulo,
        GTK_ALIGN_START
    );

    gtk_box_pack_start(
        GTK_BOX(titulo_box),
        titulo,
        FALSE,
        FALSE,
        0
    );

    subtitulo = gtk_label_new(
        "JDev Shell"
    );

    gtk_widget_set_name(
        subtitulo,
        "subtitulo"
    );

    gtk_widget_set_halign(
        subtitulo,
        GTK_ALIGN_START
    );

    gtk_box_pack_start(
        GTK_BOX(titulo_box),
        subtitulo,
        FALSE,
        FALSE,
        0
    );

    /* --------------------------------------------------------
     * ÁREA DO TERMINAL
     * -------------------------------------------------------- */

    scroll = gtk_scrolled_window_new(
        NULL,
        NULL
    );

    gtk_scrolled_window_set_policy(
        GTK_SCROLLED_WINDOW(scroll),
        GTK_POLICY_AUTOMATIC,
        GTK_POLICY_AUTOMATIC
    );

    gtk_box_pack_start(
        GTK_BOX(principal),
        scroll,
        TRUE,
        TRUE,
        0
    );

    app->saida = GTK_TEXT_VIEW(
        gtk_text_view_new()
    );

    gtk_widget_set_name(
        GTK_WIDGET(app->saida),
        "terminal"
    );

    gtk_text_view_set_editable(
        app->saida,
        FALSE
    );

    gtk_text_view_set_cursor_visible(
        app->saida,
        FALSE
    );

    gtk_text_view_set_wrap_mode(
        app->saida,
        GTK_WRAP_WORD_CHAR
    );

    gtk_container_add(
        GTK_CONTAINER(scroll),
        GTK_WIDGET(app->saida)
    );

    adicionar_saida(
        app,
        "JShell v1.0\n"
    );

    adicionar_saida(
        app,
        "Shell gráfico do JDev\n\n"
    );

    /* --------------------------------------------------------
     * LINHA DE COMANDO
     * -------------------------------------------------------- */

    linha_comando = gtk_box_new(
        GTK_ORIENTATION_HORIZONTAL,
        0
    );

    gtk_box_pack_start(
        GTK_BOX(principal),
        linha_comando,
        FALSE,
        FALSE,
        0
    );

    prompt = gtk_label_new("$");

    gtk_widget_set_name(
        prompt,
        "prompt"
    );

    gtk_box_pack_start(
        GTK_BOX(linha_comando),
        prompt,
        FALSE,
        FALSE,
        0
    );

    entrada = gtk_entry_new();

    gtk_widget_set_name(
        entrada,
        "comando"
    );

    gtk_entry_set_placeholder_text(
        GTK_ENTRY(entrada),
        "Digite um comando..."
    );

    gtk_box_pack_start(
        GTK_BOX(linha_comando),
        entrada,
        TRUE,
        TRUE,
        0
    );

    app->entrada = GTK_ENTRY(entrada);

    g_signal_connect(
        entrada,
        "activate",
        G_CALLBACK(executar_comando),
        app
    );

    /* --------------------------------------------------------
     * STATUS BAR
     * -------------------------------------------------------- */

    status = gtk_box_new(
        GTK_ORIENTATION_HORIZONTAL,
        10
    );

    gtk_widget_set_name(
        status,
        "status"
    );

    gtk_box_pack_start(
        GTK_BOX(principal),
        status,
        FALSE,
        FALSE,
        0
    );

    status_caminho = gtk_label_new(
        g_get_current_dir()
    );

    gtk_widget_set_name(
        status_caminho,
        "status"
    );

    gtk_widget_set_halign(
        status_caminho,
        GTK_ALIGN_START
    );

    gtk_box_pack_start(
        GTK_BOX(status),
        status_caminho,
        TRUE,
        TRUE,
        0
    );

    status_info = gtk_label_new(
        "READY    •    Debian 13"
    );

    gtk_widget_set_name(
        status_info,
        "status"
    );

    gtk_widget_set_halign(
        status_info,
        GTK_ALIGN_END
    );

    gtk_box_pack_end(
        GTK_BOX(status),
        status_info,
        FALSE,
        FALSE,
        0
    );

    app->status_caminho = GTK_LABEL(status_caminho);

    /* --------------------------------------------------------
     * BACKEND
     * -------------------------------------------------------- */

    if (!iniciar_backend(app)) {
        gtk_widget_set_sensitive(
            GTK_WIDGET(entrada),
            FALSE
        );
    }

    g_signal_connect(
        janela,
        "destroy",
        G_CALLBACK(fechar_backend),
        app
    );

    gtk_widget_show_all(janela);

    gtk_widget_grab_focus(entrada);
}


/* ============================================================
 * MAIN
 * ============================================================ */

int main(int argc, char **argv)
{
    GtkApplication *aplicacao;
    int status;

    aplicacao = gtk_application_new(
        "com.jdev.jshell",
        G_APPLICATION_DEFAULT_FLAGS
    );

    g_signal_connect(
        aplicacao,
        "activate",
        G_CALLBACK(ativar),
        NULL
    );

    status = g_application_run(
        G_APPLICATION(aplicacao),
        argc,
        argv
    );

    g_object_unref(aplicacao);

    return status;
}
